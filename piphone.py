#!/usr/bin/python
import RPi.GPIO as GPIO
import pyaudio
import time, math, numpy, logging

DTMF = {
    "1": [1209, 697],
    "2": [1336, 697],
    "3": [1477, 697],

    "4": [1209, 770],
    "5": [1336, 770],
    "6": [1477, 770],

    "7": [1209, 852],
    "8": [1336, 852],
    "9": [1477, 852],

    "*": [1209, 941],
    "0": [1336, 941],
    "#": [1477, 941],
}

logging.basicConfig(filename="/var/log/piphone/piphone.log", level="DEBUG",
                    format="%(asctime)-15s %(name)-8s %(module)-15s %(funcName)-15s %(message)s")
log = logging.getLogger("piphone")

class ToneGenerator(object):
    def __init__(self, samplerate=44100):
        self.samplerate = samplerate
        self.amplitude = .5
        self.buffer_offset = 0
        self.streamOpen = True
        self.frequencies = ()

    def sinewave(self, frame_count):
        out = numpy.zeros(frame_count)
        for f in self.frequencies:
            xs = numpy.arange(self.buffer_offset, self.buffer_offset + frame_count)
            omega = float(f) * (math.pi * 2) / self.samplerate
            out += self.amplitude * numpy.sin(xs * omega)
        self.buffer_offset += frame_count
        return out

    def get_next_buffer(self, frame_count):
        return self.sinewave(frame_count).astype(numpy.float32).tostring()

    # def callback(self, in_data, frame_count, time_info, status):
    #     if self.buffer_offset < self.x_max:
    #         data = self.sinewave().astype(numpy.float32)
    #         return (data.tostring(), pyaudio.paContinue)
    #     else:
    #         return (None, pyaudio.paComplete)

class Keypad(object):
    def __init__(self, button_down_callback, button_up_callback):
        GPIO.setmode(GPIO.BCM)
        self._count = 0
        self._inInterrupt = False
        self._button_down_callback = button_down_callback
        self._button_up_callback = button_up_callback

        # CONSTANTS
        self.KEYPAD = [
            ["1","2","3"],
            ["4","5","6"],
            ["7","8","9"],
            ["*","0","#"]
        ]

        #hook the rows (1,4,7,*) to these GPIO pins
        self.ROW         = [18,23,24,12]
        #hook the columns (1,2,3) to these GPIO pins
        self.COLUMN      = [4,17,22]

        self.__setInterruptMode(True)

    def __colInt(self, channel):
        time.sleep(0.05) #give it a moment to settle
        if GPIO.input(channel) > 0:
            return

        #get column number
        colVal = -1
        for c in range(len(self.COLUMN)):
            if channel == self.COLUMN[c]:
                colVal = c

        #continue if valid column (it should always be)
        if colVal >=0 and colVal < len(self.COLUMN):

            #set rows as intputs
            for r in range(len(self.ROW)):
                GPIO.setup(self.ROW[r], GPIO.IN, pull_up_down=GPIO.PUD_UP)

            #set triggered column as low output
            GPIO.setup(channel, GPIO.OUT, initial=GPIO.LOW)

            # Scan rows for pushed key/button
            rowVal = -1
            for r in range(len(self.ROW)):
                tmpRead = GPIO.input(self.ROW[r])
                if tmpRead == 0:
                    rowVal = r
                    break

            #continue if row is valid (possible that it might not be if the key was very quickly released)
            if rowVal >= 0 and rowVal < len(self.ROW):
                #send key info right away
                self._button_down_callback(self.KEYPAD[rowVal][colVal])
                #This avoids nasty bouncing errors when the key is released
                #By waiting for the rising edge before re-enabling interrupts it
                #avoids interrupts fired due to bouncing on key release and
                #any repeated interrupts that would otherwise fire.
                try:
                    GPIO.wait_for_edge(self.ROW[rowVal], GPIO.RISING)
                    self.__setInterruptMode()
                except RuntimeError:
                    pass

                self._button_up_callback(self.KEYPAD[rowVal][colVal])
                return

            else:
                log.error("Invalid Row!")
        else:
            log.error("Invalid Col!")

        #re-enable interrupts
        self.__setInterruptMode()

    def __changeWrapper(self, channel):
        #if there is already another interrupt going on (multiple key press or something)
        #return right away to avoid collisions
        if self._inInterrupt:
            return

        self._inInterrupt = True
        self.__colInt(channel) #handle the actual interrupt
        self._inInterrupt = False

    def __setInterruptMode(self, first_time=False):
        #set the first row as output low
        #only first one needed as it will ground to all columns
        for r in range(len(self.ROW)):
            GPIO.setup(self.ROW[r], GPIO.OUT, initial=GPIO.LOW)

        #set columns as inputs and attach interrupt handlers on rising edge
        #only one-time
        for c in range(len(self.COLUMN)):
            GPIO.setup(self.COLUMN[c], GPIO.IN, pull_up_down=GPIO.PUD_UP)
            if first_time:
                GPIO.add_event_detect(self.COLUMN[c], GPIO.FALLING, bouncetime=250, callback=self.__changeWrapper)

    def cleanup(self):
        GPIO.cleanup()
        log.info("Cleanup done!")


if __name__ == '__main__':
    p = pyaudio.PyAudio()
    tone = ToneGenerator(samplerate=44100/8)

    def callback(in_data, frame_count, time_info, status):
        #data = [] # length = frame_count * channels * bytes-per-channel
        return (tone.get_next_buffer(frame_count), pyaudio.paContinue)

    stream = p.open(format=pyaudio.paFloat32,
                    channels=1, rate=tone.samplerate,
                    output=True,
                    stream_callback=callback)

    def keypad_button_down(value):
        log.debug("Keypad down: " + value)
        tone.frequencies = DTMF[value]

    def keypad_button_up(value):
        log.debug("Keypad up: " + value)
        tone.frequencies = ()

    key = Keypad(keypad_button_down, keypad_button_up)

    try:
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        key.cleanup()
