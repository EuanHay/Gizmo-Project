# -*- coding: utf-8 -*-
"""
Created on Thu Jan 24 11:18:40 2019

@author: euanh
"""

# -*- coding: utf-8 -*-
"""
Spyder Editor

This is a temporary script file.
"""

""" Classes for remixing audio files.
(c) 2017 - Dave Rensin - dave@rensin.com
This module contains classes for remixing audio files. It started
as an attempt to re-create the amazing Infinite Jukebox (http://www.infinitejuke.com)
created by Paul Lamere of Echo Nest.
The InfiniteJukebox class can do it's processing in a background thread and
reports progress via the progress_callback arg. To run in a thread, pass do_async=True
to the constructor. In that case, it exposes an Event named play_ready -- which will
be signaled when the processing is complete. The default mode is to run synchronously.
  Async example:
      def MyCallback(percentage_complete_as_float, string_message):
        print "I am now %f percent complete with message: %s" % (percentage_complete_as_float * 100, string_message)
      jukebox = InfiniteJukebox(filename='some_file.mp3', progress_callback=MyCallback, do_async=True)
      jukebox.play_ready.wait()
      <some work here...>
  Non-async example:
      def MyCallback(percentage_complete_as_float, string_message):
        print "I am now %f percent complete with message: %s" % (percentage_complete_as_float * 100, string_message)
      jukebox = InfiniteJukebox(filename='some_file.mp3', progress_callback=MyCallback, do_async=False)
      <blocks until completion... some work here...>
"""

import collections
import librosa
import math
import random
import scipy
import threading

import numpy as np
import sklearn.cluster
import sklearn.metrics

class InfiniteJukebox(object):

    """ Class to "infinitely" remix a song.
    This class will take an audio file (wav, mp3, ogg, etc) and
    (a) decompose it into individual beats, (b) find the tempo
    of the track, and (c) create a play path that you can use
    to play the song approx infinitely.
    The idea is that it will find and cluster beats that are
    musically similar and return them to you so you can automatically
    'remix' the song.
    Attributes:
     play_ready: an Event that triggers when the processing/clustering is complete and
                 playback can begin. This is only defined if you pass do_async=True in the
                 constructor.
       duration: the duration (in seconds) of the track after the leading and trailing silences
                 have been removed.
      raw_audio: an array of numpy.Int16 that is suitable for using for playback via pygame
                 or similar modules. If the audio is mono then the shape of the array will
                 be (bytes,). If it's stereo, then the shape will be (2,bytes).
    sample_rate: the sample rate from the audio file. Usually 44100 or 48000
       clusters: the number of clusters used to group the beats. If you pass in a value, then
                 this will be reflected here. If you let the algorithm decide, then auto-generated
                 value will be reflected here.
          beats: a dictionary containing the individual beats of the song in normal order. Each
                 beat will have the following keys:
                         id: the ordinal position of the beat in the song
                      start: the time (in seconds) in the song where this beat occurs
                   duration: the duration (in seconds) of the beat
                     buffer: an array of audio bytes for this beat. it is just raw_audio[start:start+duration]
                    cluster: the cluster that this beat most closely belongs. Beats in the same cluster
                             have similar harmonic (timbre) and chromatic (pitch) characteristics. They
                             will "sound similar"
                    segment: the segment to which this beat belongs. A 'segment' is a contiguous block of
                             beats that belong to the same cluster.
                  amplitude: the loudness of the beat
                       next: the next beat to play after this one, if playing sequentially
            jump_candidates: a list of the other beats in the song to which it is reasonable to jump. Those beats
                             (a) are in the same cluster as the NEXT oridnal beat, (b) are of the same segment position
                             as the next ordinal beat, (c) are in the same place in the measure as the NEXT beat,
                             (d) but AREN'T the next beat.
                 An example of playing the first 32 beats of a song:
                    from Remixatron import InfiniteJukebox
                    from pygame import mixer
                    import time
                    jukebox = InfiniteJukebox('some_file.mp3')
                    pygame.mixer.init(frequency=jukebox.sample_rate)
                    channel = pygame.mixer.Channel(0)
                    for beat in jukebox.beats[0:32]:
                        snd = pygame.Sound(buffer=beat['buffer'])
                        channel.queue(snd)
                        time.sleep(beat['duration'])
    play_vector: a beat play list of 1024^2 items. This represents a pre-computed
                 remix of this song that will last beat['duration'] * 1024 * 1024
                 seconds long. A song that is 120bpm will have a beat duration of .5 sec,
                 so this playlist will last .5 * 1024 * 1024 seconds -- or 145.67 hours.
                 Each item contains:
                    beat: an index into the beats array of the beat to play
                 seq_len: the length of the musical sequence being played
                          in this part of play_vector.
                 seq_pos: this beat's position in seq_len. When
                          seq_len - seq_pos == 0 the song will "jump"
    """

    def __init__(self, filename, start_beat=1, clusters=0,
                 do_async=False, use_v1=False):

        """ The constructor for the class. Also starts the processing thread.
            Args:
                filename: the path to the audio file to process
              start_beat: the first beat to play in the file. Should almost always be 1,
                          but you can override it to skip into a specific part of the song.
                clusters: the number of similarity clusters to compute. The DEFAULT value
                          of 0 means that the code will try to automatically find an optimal
                          cluster. If you specify your own value, it MUST be non-negative. Lower
                          values will create more promiscuous jumps. Larger values will create higher quality
                          matches, but run the risk of jumps->0 -- which will just loop the
                          audio sequentially ~forever.
       progress_callback: a callback function that will get periodic satatus updates as
                          the audio file is processed. MUST be a function that takes 2 args:
                             percent_complete: FLOAT between 0.0 and 1.0
                                      message: STRING with the progress message
                  use_v1: set to True if you want to use the original auto clustering algorithm.
                          Otherwise, it will use the newer silhouette-based scheme.
        """
        self.__filename = filename
        self.__start_beat = start_beat
        self.clusters = clusters
        self._extra_diag = ""
        self._use_v1 = use_v1

        if do_async == True:
            self.play_ready = threading.Event()
            self.__thread = threading.Thread(target=self.__process_audio)
            self.__thread.start()
        else:
            self.play_ready = None
            self.__process_audio()

    def __process_audio(self):

        """ The main audio processing routine for the thread.
        This routine uses Laplacian Segmentation to find and
        group similar beats in the song.
        This code has been adapted from the sample created by Brian McFee at
        https://librosa.github.io/librosa_gallery/auto_examples/plot_segmentation.html#sphx-glr-auto-examples-plot-segmentation-py
        and is based on his 2014 paper published at http://bmcfee.github.io/papers/ismir2014_spectral.pdf
        I have made some performance improvements, but the basic parts remain (mostly) unchanged
        """

        #
        # load the file as stereo with a high sample rate and
        # trim the silences from each end
        #

        y, sr = librosa.core.load(self.__filename, mono=False, sr=None)
        y, _ = librosa.effects.trim(y)

        self.duration = librosa.core.get_duration(y,sr)
        self.raw_audio = (y * np.iinfo(np.int16).max).astype(np.int16).T.copy(order='C')
        self.sample_rate = sr

        # after the raw audio bytes are saved, convert the samples to mono
        # because the beat detection algorithm in librosa requires it.

        y = librosa.core.to_mono(y)


        # Compute the constant-q chromagram for the samples.

        BINS_PER_OCTAVE = 12 * 3
        N_OCTAVES = 7

        cqt = librosa.cqt(y=y, sr=sr, bins_per_octave=BINS_PER_OCTAVE, n_bins=N_OCTAVES * BINS_PER_OCTAVE)
        C = librosa.amplitude_to_db( np.abs(cqt), ref=np.max)

        ##########################################################
        # To reduce dimensionality, we'll beat-synchronous the CQT
        tempo, beats = librosa.beat.beat_track(y=y, sr=sr, trim=False)
        Csync = librosa.util.sync(C, beats, aggregate=np.median)

        self.tempo = tempo

        # For alignment purposes, we'll need the timing of the beats
        # we fix_frames to include non-beat frames 0 and C.shape[1] (final frame)
        beat_times = librosa.frames_to_time(librosa.util.fix_frames(beats,
                                                                    x_min=0,
                                                                    x_max=C.shape[1]),
                                            sr=sr)

        #####################################################################
        # Let's build a weighted recurrence matrix using beat-synchronous CQT
        # (Equation 1)
        # width=3 prevents links within the same bar
        # mode='affinity' here implements S_rep (after Eq. 8)
        R = librosa.segment.recurrence_matrix(Csync, width=3, mode='affinity',
                                              sym=True)

        # Enhance diagonals with a median filter (Equation 2)
        df = librosa.segment.timelag_filter(scipy.ndimage.median_filter)
        Rf = df(R, size=(1, 7))


        ###################################################################
        # Now let's build the sequence matrix (S_loc) using mfcc-similarity
        #
        #   :math:`R_\text{path}[i, i\pm 1] = \exp(-\|C_i - C_{i\pm 1}\|^2 / \sigma^2)`
        #
        # Here, we take :math:`\sigma` to be the median distance between successive beats.
        #
        mfcc = librosa.feature.mfcc(y=y, sr=sr)
        Msync = librosa.util.sync(mfcc, beats)

        path_distance = np.sum(np.diff(Msync, axis=1)**2, axis=0)
        sigma = np.median(path_distance)
        path_sim = np.exp(-path_distance / sigma)

        R_path = np.diag(path_sim, k=1) + np.diag(path_sim, k=-1)


        ##########################################################
        # And compute the balanced combination (Equations 6, 7, 9)

        deg_path = np.sum(R_path, axis=1)
        deg_rec = np.sum(Rf, axis=1)

        mu = deg_path.dot(deg_path + deg_rec) / np.sum((deg_path + deg_rec)**2)

        A = mu * Rf + (1 - mu) * R_path

        #####################################################
        # Now let's compute the normalized Laplacian (Eq. 10)
        L = scipy.sparse.csgraph.laplacian(A, normed=True)


        # and its spectral decomposition
        _, evecs = scipy.linalg.eigh(L)


        # We can clean this up further with a median filter.
        # This can help smooth over small discontinuities
        evecs = scipy.ndimage.median_filter(evecs, size=(9, 1))


        # cumulative normalization is needed for symmetric normalize laplacian eigenvectors
        Cnorm = np.cumsum(evecs**2, axis=1)**0.5

        # If we want k clusters, use the first k normalized eigenvectors.
        # Fun exercise: see how the segmentation changes as you vary k


        # if a value for clusters wasn't passed in, then we need to auto-cluster

        if self.clusters == 0:

            # if we've been asked to use the original auto clustering alogrithm, otherwise
            # use the new and improved one that accounts for silhouette scores.

            if self._use_v1:
                self.clusters, seg_ids = self.__compute_best_cluster(evecs, Cnorm)
            else:
                self.clusters, seg_ids = self.__compute_best_cluster_with_sil(evecs, Cnorm)

        else: # otherwise, just use the cluster value passed in
            k = self.clusters

            self.__report_progress( .51, "using %d clusters" % self.clusters )

            X = evecs[:, :k] / Cnorm[:, k-1:k]
            seg_ids = sklearn.cluster.KMeans(n_clusters=k, max_iter=1000,
                                             random_state=0, n_init=1000).fit_predict(X)

        # Get the amplitudes and beat-align them
        amplitudes = librosa.feature.rmse(y=y)
        ampSync = librosa.util.sync(amplitudes, beats)

        # create a list of tuples that include the ordinal position, the start time of the beat,
        # the cluster to which the beat belongs and the mean amplitude of the beat

        zbeat_tuples = zip(range(0,len(beats)), beat_times, seg_ids, ampSync[0].tolist())
        beat_tuples =tuple(zbeat_tuples)

        info = []

        bytes_per_second = int(round(len(self.raw_audio) / self.duration))

        last_cluster = -1
        current_segment = -1
        segment_beat = 0
        
        count = 0

        for i in range(0, len(beat_tuples)):
            final_beat = {}
            final_beat['start'] = float(beat_tuples[i][1])
            final_beat['cluster'] = int(beat_tuples[i][2])
            final_beat['amplitude'] = float(beat_tuples[i][3])
            print (final_beat)

            if final_beat['cluster'] != last_cluster:
                current_segment += 1
                segment_beat = 0
            else:
                segment_beat += 1

            final_beat['segment'] = current_segment
            final_beat['is'] = segment_beat

            last_cluster = final_beat['cluster']

            if i == len(beat_tuples) - 1:
                final_beat['duration'] = self.duration - final_beat['start']
            else:
                final_beat['duration'] = beat_tuples[i+1][1] - beat_tuples[i][1]

            if ( (final_beat['start'] * bytes_per_second) % 2 > 1.5 ):
                final_beat['start_index'] = int(math.ceil(final_beat['start'] * bytes_per_second))
            else:
                final_beat['start_index'] = int(final_beat['start'] * bytes_per_second)

            final_beat['stop_index'] = int(math.ceil((final_beat['start'] + final_beat['duration']) * bytes_per_second))

            # save pointers to the raw bytes for each beat with each beat.
            final_beat['buffer'] = self.raw_audio[ final_beat['start_index'] : final_beat['stop_index'] ]

            info.append(final_beat)

        # get the max amplitude of the beats
        max_amplitude = max([float(b['amplitude']) for b in info])

        # assume that the fade point of the song is the last beat of the song that is >= 75% of
        # the max amplitude.

        self.max_amplitude = max_amplitude

        fade = next(info.index(b) for b in reversed(info) if b['amplitude'] >= (.75 * max_amplitude))

        # truncate the beats to [start:fade + 1]
        beats = info[self.__start_beat:fade + 1]

        loop_bounds_begin = self.__start_beat

        # assign final beat ids
        for beat in beats:
            beat['id'] = beats.index(beat)
            beat['quartile'] = beat['id'] // (len(beats) / 4.0)

        # compute a coherent 'next' beat to play. This is always just the next ordinal beat
        # unless we're at the end of the song. Then it gets a little trickier.

        for beat in beats:
            if beat == beats[-1]:

                # if we're at the last beat, then we want to find a reasonable 'next' beat to play. It should (a) share the
                # same cluster, (b) be in a logical place in its measure, (c) be after the computed loop_bounds_begin, and
                # is in the first half of the song. If we can't find such an animal, then just return the beat
                # at loop_bounds_begin

                beat['next'] = next( (b['id'] for b in beats if b['cluster'] == beat['cluster'] and
                                      b['id'] % 4 == (beat['id'] + 1) % 4 and
                                      b['id'] <= (.5 * len(beats)) and
                                      b['id'] >= loop_bounds_begin), loop_bounds_begin )
            else:
                beat['next'] = beat['id'] + 1

            # find all the beats that (a) are in the same cluster as the NEXT oridnal beat, (b) are of the same
            # cluster position as the next ordinal beat, (c) are in the same place in the measure as the NEXT beat,
            # (d) but AREN'T the next beat, and (e) AREN'T in the same cluster as the current beat.
            #
            # THAT collection of beats contains our jump candidates

            jump_candidates = [bx['id'] for bx in beats[loop_bounds_begin:] if
                               (bx['cluster'] == beats[beat['next']]['cluster']) and
                               (bx['is'] == beats[beat['next']]['is']) and
                               (bx['id'] % 4 == beats[beat['next']]['id'] % 4) and
                               (bx['segment'] != beat['segment']) and
                               (bx['id'] != beat['next'])]

            if jump_candidates:
                beat['jump_candidates'] = jump_candidates
            else:
                beat['jump_candidates'] = []

        # save off the segment count
        self.segments = max([b['segment'] for b in beats]) + 1

        # we don't want to ever play past the point where it's impossible to loop,
        # so let's find the latest point in the song where there are still jump
        # candidates and make sure that we can't play past it.

        last_chance = next(beats.index(b) for b in reversed(beats) if len(b['jump_candidates']) > 0)

        # if we play our way to the last beat that has jump candidates, then just skip
        # to the earliest jump candidate rather than enter a section from which no
        # jumping is possible.

        beats[last_chance]['next'] = min(beats[last_chance]['jump_candidates'])

        # store the beats that start after the last jumpable point. That's
        # the outro to the song. We can use these
        # beasts to create a sane ending for a fixed-length remix

        outro_start = last_chance + 1 + self.__start_beat

        if outro_start >= len(info):
            self.outro = []
        else:
            self.outro = info[outro_start:]

        #
        # This section of the code computes the play_vector -- a 1024*1024 beat length
        # remix of the current song.
        #

        random.seed()

        # how long should our longest contiguous playback blocks be? One way to
        # consider it is that higher bpm songs need longer blocks because
        # each beat takes less time. A simple way to estimate a good value
        # is to scale it by it's distance from 120bpm -- the canonical bpm
        # for popular music. Find that value and round down to the nearest
        # multiple of 4. (There almost always are 4 beats per measure in Western music).

        max_sequence_len = int(round((self.tempo / 120.0) * 48.0))
        max_sequence_len = max_sequence_len - (max_sequence_len % 4)

        min_sequence = max(random.randrange(16, max_sequence_len, 4), loop_bounds_begin)

        current_sequence = 0
        beat = beats[0]

        play_vector = []

        play_vector.append( {'beat':0, 'seq_len':min_sequence, 'seq_pos':current_sequence} )

        # we want to keep a list of recently played segments so we don't accidentally wind up in a local loop
        #
        # the number of segments in a song will vary so we want to set the number of recents to keep
        # at 25% of the total number of segments. Eg: if there are 34 segments, then the depth will
        # be set at round(8.5) == 9.
        #
        # On the off chance that the (# of segments) *.25 < 1 we set a floor queue depth of 1
        
        print(play_vector)

        recent_depth = int(round(self.segments * .25))
        recent_depth = max( recent_depth, 1 )

        recent = collections.deque(maxlen=recent_depth)

        # keep track of the time since the last successful jump. If we go more than
        # 10% of the song length since our last jump, then we will prioritize an
        # immediate jump to a not recently played segment. Otherwise playback will
        # be boring for the listener. This also has the advantage of busting out of
        # local loops.

        max_beats_between_jumps = int(round(len(beats) * .1))
        beats_since_jump = 0
        failed_jumps = 0
        
        count = 0
        score = 0
        
        print ("LENGTH")
        print (len(beats))
        
        led_positions = []
        new_candidates = []
        candidate_id = []
        led_time = []
        duration1 = 0
        time_of_beat = []
        

        for i in range(0, 1024 * 1024): #For every beat
            #print (beat)
            if duration1 <= 180.5: #We only need 3 minutes of data, not 1024*1024
                #print(beat['id'])
                #print (beat['jump_candidates'])
                #print("DURATION")
                #print(beat['duration'])
                #print("Start")
                #print(beat["start"])
                duration1 += beat['duration']
                candidate_id.append(beat['id']) #Which beat is currently being played?
                new_candidates.append(beat['jump_candidates']) #What are the suitable beats to jump to from this beat?
                led_positions.append(int(((play_vector[count]["beat"])/(len(beats))*60))) #Which LED should be lit up from the 60-LED ring?
                led_time.append(beat['start'])
                time_of_beat.append(duration1)
                count += 1
                score +=1
            if beat['segment'] not in recent:
                recent.append(beat['segment'])

            current_sequence += 1

            # it's time to attempt a jump if we've played all the beats we wanted in the
            # current sequence. Also, if we've gone more than 10% of the length of the song
            # without jumping we need to immediately prioritze jumping to a non-recent segment.

            will_jump = (current_sequence == min_sequence) or (beats_since_jump >= max_beats_between_jumps)

            # since it's time to jump, let's find the most musically pleasing place
            # to go

            if ( will_jump ):

                # find the jump candidates that haven't been recently played
                non_recent_candidates = [c for c in beat['jump_candidates'] if beats[c]['segment'] not in recent]

                # if there aren't any good jump candidates, then we need to fall back
                # to another selection scheme.

                if len(non_recent_candidates) == 0:

                    beats_since_jump += 1
                    failed_jumps += 1

                    # suppose we've been trying to jump but couldn't find a good non-recent candidate. If
                    # the length of time we've been trying (and failing) is >= 10% of the song length
                    # then it's time to relax our criteria. Let's find the jump candidate that's furthest
                    # from the current beat (irrespective if it's been played recently) and go there. Ideally
                    # we'd like to jump to a beat that is not in the same quartile of the song as the currently
                    # playing section. That way we maximize our chances of avoiding a long local loop -- such as
                    # might be found in the section preceeding the outro of a song.

                    non_quartile_candidates = [c for c in beat['jump_candidates'] if beats[c]['quartile'] != beat['quartile']]

                    if (failed_jumps >= (.1 * len(beats))) and (len(non_quartile_candidates) > 0):

                        furthest_distance = max([abs(beat['id'] - c) for c in non_quartile_candidates])

                        jump_to = next(c for c in non_quartile_candidates
                                       if abs(beat['id'] - c) == furthest_distance)

                        beat = beats[jump_to]
                        beats_since_jump = 0
                        failed_jumps = 0

                    # uh oh! That fallback hasn't worked for yet ANOTHER 10%
                    # of the song length. Something is seriously broken. Time
                    # to punt and just start again from the first beat.

                    elif failed_jumps >= (.2 * len(beats)):
                        beats_since_jump = 0
                        failed_jumps = 0
                        beat = beats[loop_bounds_begin]

                    # asuuming we're not in one of the failure modes but haven't found a good
                    # candidate that hasn't been recently played, just play the next beat in the
                    # sequence

                    else:
                        beat = beats[beat['next']]
                        #print ("ID")
                        #print (beat["id"])
                        #print (beat["next"])
                        #print (beat["jump_candidates"])
                        #print (beat)
                        #print(play_vector[count])
                        #if (play_vector[count]["seq_pos"]) == (play_vector[count]["seq_len"])-1:
                            #print ("JUMP")
                            
                        #print(play_vector[count]["beat"])
                        #print ("LENGTH")
                        #print (len(beats))
                        #print ("SONG POSITION")
                        #print (int(((play_vector[count]["beat"])/(len(beats))*60)))
                        #led_positions.append(int(((play_vector[count]["beat"])/(len(beats))*60)))
                        #count+=1

                else:

                    # if it's time to jump and we have at least one good non-recent
                    # candidate, let's just pick randomly from the list and go there

                    beats_since_jump = 0
                    failed_jumps = 0
                    beat = beats[ random.choice(non_recent_candidates) ]

                # reset our sequence position counter and pick a new target length
                # between 8 and max_sequence_len, making sure it's evenly divisible by
                # 4 beats

                current_sequence = 0
                min_sequence = random.randrange(16, max_sequence_len, 4)

                # if we're in the place where we want to jump but can't because
                # we haven't found any good candidates, then set current_sequence equal to
                # min_sequence. During playback this will show up as having 00 beats remaining
                # until we next jump. That's the signal that we'll jump as soon as we possibly can.
                #
                # Code that reads play_vector and sees this value can choose to visualize this in some
                # interesting way.

                if beats_since_jump >= max_beats_between_jumps:
                    current_sequence = min_sequence

                # add an entry to the play_vector
                play_vector.append({'beat':beat['id'], 'seq_len': min_sequence, 'seq_pos': current_sequence})
            else:

                # if we're not trying to jump then just add the next item to the play_vector
                play_vector.append({'beat':beat['next'], 'seq_len': min_sequence, 'seq_pos': current_sequence})
                beat = beats[beat['next']]
                beats_since_jump += 1

        # save off the beats array and play_vector. Signal
        # the play_ready event (if it's been set)
        #print (play_vector)
        self.beats = beats
        self.play_vector = play_vector
        
        with open('positions3.txt', 'w') as f: #Lines 620-638 add the necessary data to the list
            for item in led_positions:
                f.write("%s\n" % item)
                
        with open('candidates3.txt', 'w') as f:
            for item in new_candidates:
                f.write("%s\n" % item)
                
        with open('beat_id3.txt', 'w') as f:
            for item in candidate_id:
                f.write("%s\n" % item)
                
        with open('time3.txt', 'w') as f:
            for item in led_time:
                f.write("%s\n" % item)
                
        with open('time_of_beat3.txt', 'w') as f:
            for item in time_of_beat:
                f.write("%s\n" % item)

        if self.play_ready:
            self.play_ready.set()


    def __compute_best_cluster_with_sil(self, evecs, Cnorm):

        ''' Attempts to compute optimum clustering
            Uses the the silhouette score to pick the best number of clusters.
            See: https://en.wikipedia.org/wiki/Silhouette_(clustering)
            PARAMETERS:
                evecs: Eigen-vectors computed from the segmentation algorithm
                Cnorm: Cumulative normalization of evecs. Easier to pass it in than
                       compute it from scratch here.
            KEY DEFINITIONS:
                  Clusters: buckets of musical similarity
                  Segments: contiguous blocks of beats belonging to the same cluster
                Silhouette: A score given to a cluster that measures how well the cluster
                            members fit together. The value is from -1 to +1. Higher values
                            indicated higher quality.
            SUMMARY:
                From testing, I observe that clusters with segment/cluster ratios greater than 3.0
                produce the best musical effects. There may, of course be many such cluster
                choices. This alogrithm selects the highest cluster value with a ratio >= 3.0
                AND an average silhouette score > .4.
                Why not just pick the cluster with the highest silhouette score?
                There's a tradeoff to make. The higher the clusters, the higher the quality of the
                jumps will be because the average distance between any two beat in the same cluster
                will be smaller.
                On the other hand, there needs to be at least a minimum silhouette threshold. Based
                on my testing, these aggregate parameters produce the best results.
                If you're an ML person, you can think of this as hyperparameter tuning.
        '''

        self._clusters_list = []

        best_cluster_size = 0
        best_labels = None

        for n_clusters in range(3,49,1):

            # compute a matrix of the Eigen-vectors / their normalized values
            X = evecs[:, :n_clusters] / Cnorm[:, n_clusters-1:n_clusters]

            # create the candidate clusters and fit them
            clusterer = sklearn.cluster.KMeans(n_clusters=n_clusters, max_iter=300,
                                               random_state=0, n_init=20)

            cluster_labels = clusterer.fit_predict(X)

            # get some key statistics, including how well each beat in the cluster resemble
            # each other (the silhouette average), the ratio of segments to clusters, and the
            # length of the smallest segment in this cluster configuration

            silhouette_avg = sklearn.metrics.silhouette_score(X, cluster_labels)

            ratio, min_segment_len = self.__segment_stats_from_labels(cluster_labels.tolist())

            # There are a few key heuristics we can look at to see if we have a good solution.
            # Firstly, we want to make sure the that segment-to-cluster ratio is at least 2.5.
            # That means that (on average) each cluster is represented in at least 2.5 segments.
            # Why this value? Because it tends to produce good results. (If you're looking for a
            # solid theoretical underpinning for these hyperparameters, you'll need to look
            # elsewhere. :-))
            #
            # Next, we want to make sure that the beats in each cluster meet a minimum threshold
            # for similarity. That's represented by the silhoueete average. In this case, we'll
            # select a threshold of .5.
            #
            # Finally, if we find that we have segments with only one beat, that's a pretty good
            # hint that we've overfit. So, we make sure that the smallest segment in each
            # candidate cluster is greather than 1 beat long.

            if (ratio >= 2.5) and (silhouette_avg >= .5) and (min_segment_len > 1):
                best_cluster_size = n_clusters
                best_labels = cluster_labels

        # if we found an acceptable answer, the return it. Otherwise, return
        # the results of the old clustering algorithm.

        if best_cluster_size != 0:

            # re-cluster with the selected size, but much higher iteration values.

            X = evecs[:, :best_cluster_size] / Cnorm[:, best_cluster_size-1:best_cluster_size]
            best_labels = sklearn.cluster.KMeans(n_clusters=best_cluster_size, max_iter=1000,
                                                 random_state=0, n_init=1000).fit_predict(X)
            return (best_cluster_size, best_labels)
        else:

            # well... That didn't work, so fallback to the V1 clustering algorithm.
            self.__report_progress( .51, "couldn't find any good candidates. Falling back to the v1 clustering algorithm..." )
            return self.__compute_best_cluster(evecs, Cnorm)

    @staticmethod
    def __segment_count_from_labels(labels):

        ''' Computes the number of unique segments from a set of ordered labels. Segements are
            contiguous beats that belong to the same cluster. '''

        segment_count = 0
        previous_label = -1

        for label in labels:
            if label != previous_label:
                previous_label = label
                segment_count += 1

        return segment_count

    def __segment_stats_from_labels(self, labels):
        ''' Computes the segment/cluster ratio and min segment size value given an array
            of labels. '''

        segment_count = 0.0
        segment_length = 0
        clusters = max(labels) + 1

        previous_label = -1

        segment_lengths = []

        for label in labels:
            if label != previous_label:
                previous_label = label
                segment_count += 1.0

                if segment_length > 0:
                    segment_lengths.append(segment_length)

                segment_length = 1
            else:
                segment_length +=1


        return float(segment_count) / float(clusters), min(segment_lengths)

    def __compute_best_cluster(self, evecs, Cnorm):

        ''' Attempts to compute optimum clustering from a set of simplified
            hueristics. This method has been deprecated in favor of code above that takes into
            account the average silhouette score of each cluster. You can force the code to use
            this method by passing in use_v1=True in the constructor.
            PARAMETERS:
                evecs: Eigen-vectors computed from the segmentation algorithm
                Cnorm: Cumulative normalization of evecs. Easier to pass it in than
                       compute it from scratch here.
            KEY DEFINITIONS:
                Clusters: buckets of musical similarity
                Segments: contiguous blocks of beats belonging to the same cluster
                 Orphans: clusters that only belong to one segment
                    Stub: a cluster with less than N beats. Stubs are a sign of
                          overfitting
            SUMMARY:
                Group the beats in [8..64] clusters. They key metric is the segment:cluster ratio.
                This value gives the avg number of different segments to which a cluster
                might belong. The higher the value, the more diverse the playback because
                the track can jump more freely. There is a balance, however, between this
                ratio and the number of clusters. In general, we want to find the highest
                numeric cluster that has a ratio of segments:clusters nearest 4.
                That ratio produces the most musically pleasing results.
                Basically, we're looking for the highest possible cluster # that doesn't
                obviously overfit.
                Someday I'll implement a proper RMSE algorithm...
        '''

        self._clusters_list = []

        # We compute the clusters between 4 and 64. Owing to the inherent
        # symmetry of Western popular music (including Jazz and Classical), the most
        # pleasing musical results will often, though not always, come from even cluster values.

        for ki in range(4,64, 2):

            # compute a matrix of the Eigen-vectors / their normalized values
            X = evecs[:, :ki] / Cnorm[:, ki-1:ki]

            # cluster with candidate ki
            labels = sklearn.cluster.KMeans(n_clusters=ki, max_iter=1000,
                                            random_state=0, n_init=20).fit_predict(X)

            entry = {'clusters':ki, 'labels':labels}

            # create an array of dictionary entries containing (a) the cluster label,
            # (b) the number of total beats that belong to that cluster, and
            # (c) the number of segments in which that cluster appears.

            lst = []

            for i in range(0,ki):
                lst.append( {'label':i, 'beats':0, 'segs':0} )

            last_label = -1

            for l in labels:

                if l != last_label:
                    lst[l]['segs'] += 1
                    last_label = l

                lst[l]['beats'] += 1

            entry['cluster_map'] = lst

            # get the average number of segments to which a cluster belongs
            entry['seg_ratio'] = np.mean([l['segs'] for l in entry['cluster_map']])

            self._clusters_list.append(entry)

        # get the max cluster with the segments/cluster ratio nearest to 4. That
        # will produce the most musically pleasing effect

        max_seg_ratio = max( [cl['seg_ratio'] for cl in self._clusters_list] )
        max_seg_ratio = min( max_seg_ratio, 4 )

        final_cluster_size = max(cl['clusters'] for cl in self._clusters_list if cl['seg_ratio'] >= max_seg_ratio)

        # compute a very high fidelity set of clusters using our selected cluster size.
        X = evecs[:, :final_cluster_size] / Cnorm[:, final_cluster_size-1:final_cluster_size]
        labels = sklearn.cluster.KMeans(n_clusters=final_cluster_size, max_iter=1000,
                                        random_state=0, n_init=1000).fit_predict(X)

        # labels = next(c['labels'] for c in self._clusters_list if c['clusters'] == final_cluster_size)

        # return a tuple of (winning cluster size, [array of cluster labels for the beats
        return (final_cluster_size, labels)

    def __add_log(self, line):
        """Convenience method to add debug logging info for later"""

        self._extra_diag += line + "\n"