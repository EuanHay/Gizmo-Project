# -*- coding: utf-8 -*-
"""
Created on Tue Jan 22 14:07:07 2019

@author: euanh
"""

import argparse
import curses
import curses.textpad
import numpy as np
import os
import pygame
import pygame.event
import pygame.locals
import signal
import soundfile as sf
import sys
import time

from remixatron_copy import InfiniteJukebox
from pygame import mixer

SOUND_FINISHED = pygame.locals.USEREVENT + 1

def process_args():

    """ Process the command line args """

    description = """Creates an infinite remix of an audio file by finding musically similar beats and computing a randomized play path through them. The default choices should be suitable for a variety of musical styles. This work is inspired by the Infinite Jukebox (http://www.infinitejuke.com) project creaeted by Paul Lamere (paul@spotify.com)"""

    epilog = """
    """

    parser = argparse.ArgumentParser(description=description, epilog=epilog, formatter_class=argparse.RawDescriptionHelpFormatter)

    parser.add_argument("filename", type=str,
                        help="the name of the audio file to play. Most common audio types should work. (mp3, wav, ogg, etc..)")

    parser.add_argument("-clusters", metavar='N', type=int, default=0,
                        help="set the number of clusters into which we want to bucket the audio. Default: 0 (automatically try to find the optimal cluster value.)")

    parser.add_argument("-start", metavar='start_beat', type=int, default=1,
                        help="start on a specific beat. Default: 1")

    parser.add_argument("-save", metavar='label', type=str,
                        help="Save the remix to a file, rather than play it. Will create file named [label].wav")

    parser.add_argument("-duration", metavar='seconds', type=int, default=180,
                        help="length (in seconds) to save. Must use with -save. Default: 180")

    parser.add_argument("-verbose", action='store_true',
                        help="print extra info about the track and play vector")

    parser.add_argument("-use_v1", action='store_true',
                        help="use the original auto clustering algorithm instead of the new one. -clusters must not be set.")

    return parser.parse_args()


def save_to_file(jukebox, label, duration):
    ''' Save a fixed length of audio to disk. '''

    avg_beat_duration = 60 / jukebox.tempo
    num_beats_to_save = int(duration / avg_beat_duration)

    # this list comprehension returns all the 'buffer' arrays from the beats
    # associated with the [0..num_beats_to_save] entries in the play vector

    main_bytes = [jukebox.beats[v['beat']]['buffer'] for v in jukebox.play_vector[0:num_beats_to_save]]

    # main_bytes is an array of byte[] arrays. We need to flatten it to just a
    # regular byte[]

    output_bytes = np.concatenate( main_bytes )

    # write out the wav file
    sf.write(label + '.wav', output_bytes, jukebox.sample_rate, format='WAV', subtype='PCM_24')


if __name__ == "__main__":

    # store the original SIGINT handler and install a new handler
    original_sigint = signal.getsignal(signal.SIGINT)


    #
    # Main program logic
    #

    window = None

    args = process_args()

    # do the clustering. Run synchronously. Post status messages to MyCallback()
    jukebox = InfiniteJukebox(filename=args.filename, start_beat=args.start, clusters=args.clusters,
                                 do_async=False, use_v1=args.use_v1)
    
    print ("Saving")
    save_to_file(jukebox, "feelGoodMix", 180)
    print ("Finished")
    # if we're just saving the remix to a file, then just
    # find the necessarry beats and do that


    # it's important to make sure the mixer is setup with the
    # same sample rate as the audio. Otherwise the playback will
    # sound too slow/fast/awful

    mixer.init(frequency=jukebox.sample_rate)
    channel = mixer.Channel(0)

    # pygame's event handling functions won't work unless the
    # display module has been initialized -- even though we
    # won't be making any display calls.

    pygame.display.init()

    # register the event type we want fired when a sound buffer
    # finishes playing

    channel.set_endevent(SOUND_FINISHED)

    # queue and start playing the first event in the play vector. This is basic
    # audio double buffering that will reduce choppy audio from impercise timings. The
    # goal is to always have one beat in queue to play as soon as the last one is done.

    beat_to_play = jukebox.beats[ jukebox.play_vector[0]['beat'] ]

    snd = mixer.Sound(buffer=beat_to_play['buffer'])
    channel.queue(snd)

    # go through the rest of  the playback list, start playing each beat, display
    # the progress and wait for the playback to complete. Playback happens on another
    # thread in the pygame library, so we have to wait to be signaled to queue another
    # event.

    for v in jukebox.play_vector[1:]:

        beat_to_play = jukebox.beats[ v['beat'] ]

        snd = mixer.Sound(buffer=beat_to_play['buffer'])
        channel.queue(snd)

        pygame.event.wait()
