# https://micronote.tech
# This code is designed specifically for the Atlas kit.
#
# Edit button callback functions to change outcome of button presses.
#
# Button callbacks:
# - Mode: mode_button_callback
# - Decr: decr_button_callback
# - Incr: incr_button_callback

from machine import Pin, SPI, Timer, RTC
import network
import time

_NOOP = 0x0
_DIGIT0 = 0x1
_DIGIT1 = 0x2
_DIGIT2 = 0x3
_DIGIT3 = 0x4
_DIGIT4 = 0x5
_DIGIT5 = 0x6
_DECODE_MODE = 0x9

_DIGIT_DICT = {
    0: _DIGIT0,
    1: _DIGIT1,
    2: _DIGIT2,
    3: _DIGIT3,
    4: _DIGIT4,
    5: _DIGIT5,
}

_DP = 0x80

_RED_LED_PIN = 0
_GREEN_LED_PIN = 4
_BLUE_LED_PIN = 5

_MODE_BUTTON_PIN = 12
_INCR_BUTTON_PIN = 10
_DECR_BUTTON_PIN = 2

_SPI_CS_PIN = 15

_BUZZER = 16

_MAX_VALUE_DEC = 999999
_MIN_VALUE_DEC = -99999
_MAX_VALUE_HEX = 0xFFFFFF
_MIN_VALUE_HEX = 0x000000
_MAX_VALUE_DP = 0b111111
_MIN_VALUE_DP = 0b000000

_DEBOUNCE_SAMPLES = 32

_DECODE_MODE = 9
_INTENSITY = 10
_SCAN_LIMIT = 11
_SHUTDOWN = 12
_DISPLAY_TEST = 15

_HEX_TO_SEG = {
    0x0: 0b1111110,
    0x1: 0b0110000,
    0x2: 0b1101101,
    0x3: 0b1111001,
    0x4: 0b0110011,
    0x5: 0b1011011,
    0x6: 0b1011111,
    0x7: 0b1110000,
    0x8: 0b1111111,
    0x9: 0b1111011,
    0xA: 0b1110111,
    0xB: 0b0011111,
    0xC: 0b1001110,
    0xD: 0b0111101,
    0xE: 0b1001111,
    0xF: 0b1000111,
}


class Atlas:
    def __init__(self):
        
        # initialize LEDs
        self.red_led = Pin(_RED_LED_PIN, Pin.OUT)
        self.green_led = Pin(_GREEN_LED_PIN, Pin.OUT)
        self.blue_led = Pin(_BLUE_LED_PIN, Pin.OUT)
        self.leds = [self.red_led, self.green_led, self.blue_led]
        self.red_led.value(0)
        self.green_led.value(0)
        self.blue_led.value(0)
        
        # initialize buzzer
        self.buzzer = Pin(_BUZZER, Pin.OUT)
        self.buzzer.value(1)
        self.note_timer = Timer(2)
        self.note_timer.deinit()
        
        # initialize SPI
        self._spi = SPI(1, baudrate=10000000, polarity=1, phase=0)
        self._cs = Pin(_SPI_CS_PIN)
        self._cs.init(self._cs.OUT, True)

        # initialize displays
        self._register(_SHUTDOWN, 0)
        self._register(_DISPLAY_TEST, 0)
        self._register(_SCAN_LIMIT, 7)
        self._register(_DECODE_MODE, 0)
        self._register(_SHUTDOWN, 1)
        self.display_clear()
        self.display_brightness(5)
        
        # initialize buttons with pullup resistors
        self.mode_button = Pin(_MODE_BUTTON_PIN, Pin.IN, Pin.PULL_UP)
        self.incr_button = Pin(_INCR_BUTTON_PIN, Pin.IN, Pin.PULL_UP)
        self.decr_button = Pin(_DECR_BUTTON_PIN, Pin.IN, Pin.PULL_UP)
        self.mode_button.irq(trigger=Pin.IRQ_FALLING, handler=self.mode_button_callback)
        self.incr_button.irq(trigger=Pin.IRQ_FALLING, handler=self.incr_button_callback)
        self.decr_button.irq(trigger=Pin.IRQ_FALLING, handler=self.decr_button_callback)

        # initialize current number and current decimal points
        self.current_num = None
        self.current_dp = 0b000000

        # initialize timer and rtc
        self.sta_if = network.WLAN(network.STA_IF)
        self.rtc = RTC()

    # connect to wifi
    def connect_to_wifi(self, ssid, password):
        if not self.sta_if.isconnected():
            print('Connecting to network...')
            self.sta_if.active(True)
            self.sta_if.connect(ssid, password)
            while not self.sta_if.isconnected():
                print('.', end='')
                time.sleep(1)
        print('Connected!')
    
    # set the display brightness
    def display_brightness(self, value):
        if 0 <= value <= 15:
            self._register(_INTENSITY, value)
        else:
            raise ValueError("Brightness out of range")

    # clear the display
    def display_clear(self):
        self._register(_DECODE_MODE, 0xFF)
        for i in range(6):
            self._register(_DIGIT_DICT[i], 0x0F)

        self.current_num = None

    # write a decimal value to the display, dp is 6 bit binary value representing where to put decimal points
    def write_num(self, value, dp=0b000000):
        self._register(_DECODE_MODE, 0xFF)

        if (0 <= value <= _MAX_VALUE_DEC) and (_MIN_VALUE_DP <= dp <= _MAX_VALUE_DP):
            self.current_num = value
            self.current_dp = dp

            for i in range(6):
                current_value = value % 10

                if dp & 1:
                    self._register(_DIGIT_DICT[i], current_value | _DP)
                else:
                    self._register(_DIGIT_DICT[i], current_value)

                dp = dp >> 1
                value = value // 10

        elif (0 > value >= _MIN_VALUE_DEC) and (_MIN_VALUE_DP <= dp <= _MAX_VALUE_DP):
            self.current_num = value
            self.current_dp = dp

            value = -value
            self._register(_DIGIT5, 0xA)

            for i in range(5):
                current_value = value % 10

                if dp & 1:
                    self._register(_DIGIT_DICT[i], current_value | _DP)
                else:
                    self._register(_DIGIT_DICT[i], current_value)

                dp = dp >> 1
                value = value // 10

        else:
            raise ValueError("Value out of range")

    # toggle a GPIO pin
    @staticmethod
    def toggle_pin(pin):
        pin.value(not (pin.value()))
        
    # callback for buzzer
    def buzzer_callback(self, pin):
        self.toggle_pin(self.buzzer)

    # play a note
    def play_note(self, freq):
        self.note_timer.init(freq=freq, mode=Timer.PERIODIC, callback=self.buzzer_callback)
    
    # stop playing a note
    def stop_note(self):
        self.note_timer.deinit()
        self.buzzer.value(1)
        
    # increment the current number on the display
    def increment_num(self):
        if self.current_num is None:
            raise ValueError("No value to increment")
        else:
            if (self.current_num + 1) > _MAX_VALUE_DEC:
                self.current_num = -1

            self.write_num(self.current_num + 1, self.current_dp)

    # decrement the current number on the display
    def decrement_num(self):
        if self.current_num is None:
            raise ValueError("No value to decrement")
        else:
            if (self.current_num - 1) < _MIN_VALUE_DEC:
                self.current_num = 1

            self.write_num(self.current_num - 1, self.current_dp)

    # callback for mode button
    def mode_button_callback(self, pin):
        if self._debounce(self.mode_button):
            for led in self.leds:
                self.toggle_pin(led)

    # callback for incr Button
    def incr_button_callback(self, pin):
        if self._debounce(self.incr_button):
            self.increment_num()

    # callback for decr button
    def decr_button_callback(self, pin):
        if self._debounce(self.decr_button):
            self.decrement_num()
    
    # send commands to MAX7219
    def _register(self, command, data):
        self._cs.value(0)
        self._spi.write(bytearray([command, data]))
        self._cs.value(1)

    # debounce buttons
    @staticmethod
    def _debounce(button):
        flag = 0

        for i in range(_DEBOUNCE_SAMPLES):
            flag = button.value()
            if button.value():
                return not flag

        return not flag
