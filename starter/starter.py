# https://micronote.tech
# This code is designed specifically for the wifi clock kit.
#
# Edit button callback functions to change outcome of button presses.
#
# Button callbacks:
# - Mode: mode_button_callback
# - Decr: decr_button_callback
# - Incr: incr_button_callback
# 
# Edit timer callback function to change outcome of timer period.
#
# Timer callback: clock_timer_callback

from machine import Pin, SPI, Timer, RTC
import network
import time
import ntptime

_NOOP = 0x0
_DIGIT0 = 0x3
_DIGIT1 = 0x2
_DIGIT2 = 0x1
_DIGIT3 = 0x6
_DIGIT4 = 0x5
_DIGIT5 = 0x4
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

_RED_LED_PIN = 12
_GREEN_LED_PIN = 13
_BLUE_LED_PIN = 15

_MODE_BUTTON_PIN = 14
_INCR_BUTTON_PIN = 2
_DECR_BUTTON_PIN = 0

_SPI_MOSI_PIN = 5
_SPI_MISO_PIN = 12
_SPI_CLK_PIN = 16
_SPI_CS_PIN = 4

_MAX_VALUE_DEC = 999999
_MIN_VALUE_DEC = -99999
_MAX_VALUE_HEX = 0xFFFFFF
_MIN_VALUE_HEX = 0x000000
_MAX_VALUE_DP = 0b111111
_MIN_VALUE_DP = 0b000000

_DEBOUNCE_SAMPLES = 32

_INTENSITY = 0xA
_SCAN_LIMIT = 0xB
_SHUTDOWN = 0xC
_DISPLAY_TEST = 0xF

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


class WifiClock:
    def __init__(self):

        # Initialize SPI
        self._spi = SPI(-1, baudrate=10000000, polarity=1, phase=0, sck=Pin(_SPI_CLK_PIN), mosi=Pin(_SPI_MOSI_PIN), miso=Pin(_SPI_MISO_PIN))
        self._cs = Pin(_SPI_CS_PIN)
        self._cs.init(self._cs.OUT, True)

        # Initialize LEDs
        self.red_led = Pin(_RED_LED_PIN, Pin.OUT)
        self.green_led = Pin(_GREEN_LED_PIN, Pin.OUT)
        self.blue_led = Pin(_BLUE_LED_PIN, Pin.OUT)

        # Initialize buttons with interrupts
        self.mode_button = Pin(_MODE_BUTTON_PIN, Pin.IN, Pin.PULL_UP)
        self.mode_button.irq(trigger=Pin.IRQ_FALLING, handler=self.mode_button_callback)
        self.incr_button = Pin(_INCR_BUTTON_PIN, Pin.IN, Pin.PULL_UP)
        self.incr_button.irq(trigger=Pin.IRQ_FALLING, handler=self.incr_button_callback)
        self.decr_button = Pin(_DECR_BUTTON_PIN, Pin.IN, Pin.PULL_UP)
        self.decr_button.irq(trigger=Pin.IRQ_FALLING, handler=self.decr_button_callback)

        # Initialize current number and current decimal points
        self.current_num = None
        self.current_dp = 0b000000

        # Initialize timer and rtc
        self.sta_if = network.WLAN(network.STA_IF)
        self.rtc = RTC()
        self.timer = Timer(1)

        for command, data in (
            (_SHUTDOWN, 0),
            (_SCAN_LIMIT, 7),
            (_DECODE_MODE, 0xFF),
            (_INTENSITY, 0xa),
            (_SHUTDOWN, 1),
        ):
            self._register(command, data)

        self.display_clear()
        self.red_led.value(0)
        self.green_led.value(0)
        self.blue_led.value(0)

    # Connect to wifi
    def connect_to_wifi(self, ssid, password):
        if not self.sta_if.isconnected():
            print('Connecting to network...')
            self.sta_if.active(True)
            self.sta_if.connect(ssid, password)
            while not self.sta_if.isconnected():
                print('.', end='')
                time.sleep(1)
        print('Connected!')

    # Set time manually
    def set_time(self, hour, minute, second):
        self.rtc.datetime((2019, 1, 1, 0, hour, minute, second, 0))

    # Set time using ntp server (must be connected to wifi)
    def set_time_ntp(self, utc_offset):
        ntptime.settime()
        d = self.rtc.datetime()

        hour = d[4] + utc_offset

        if hour < 0:
            hour = 24 + hour 
        elif hour > 23:
            hour = hour - 24

        d = (d[0], d[1], d[2], d[3], hour, d[5], d[6], d[7]) 
        self.rtc.datetime(d)

    # Start a 24 hour clock (call after setting the time either with set_time or set_time_ntp)
    def start_clock24(self):
        self.timer.init(period=1000, mode=Timer.PERIODIC, callback=self.clock_timer_callback)
    
    # Set the display brightness
    def display_brightness(self, value):
        if 0 <= value <= 15:
            self._register(_INTENSITY, value)
        else:
            raise ValueError("Brightness out of range")

    # Clear the display
    def display_clear(self):
        self._register(_DECODE_MODE, 0xFF)
        for i in range(6):
            self._register(_DIGIT_DICT[i], 0x0F)

        self.current_num = None;

    # Write a decimal value to the display, dp is 6 bit binary value representing where to put decimal points
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

    # Write literal hex value to the display
    def write_hex(self, value):
        self._register(_DECODE_MODE, 0x0)
        if 0x0 <= value <= _MAX_VALUE_HEX:

            self.current_num = value

            for i in range(6):
                self._register(_DIGIT_DICT[i], _HEX_TO_SEG[value % 16])
                value = value // 16
        else:
            raise ValueError("Value out of range")

    # Toggle an LED
    @staticmethod
    def toggle_led(led):
        led.value(not (led.value()))

    # Increment the current number on the display
    def increment_num(self, hex=False):
        if self.current_num is None:
            raise ValueError("No value to increment")
        else:

            if hex:
                if (self.current_num + 1) > _MAX_VALUE_HEX:
                    self.current_num = -1

                self.write_hex(self.current_num + 1)
            else:

                if (self.current_num + 1) > _MAX_VALUE_DEC:
                    self.current_num = -1

                self.write_num(self.current_num + 1, self.current_dp)

    # Decrement the current number on the display
    def decrement_num(self, hex=False):
        if self.current_num is None:
            raise ValueError("No value to decrement")
        else:

            if hex:
                if (self.current_num - 1) < _MIN_VALUE_HEX:
                    self.current_num = 1

                self.write_hex(self.current_num - 1)
            else:

                if (self.current_num - 1) < _MIN_VALUE_DEC:
                    self.current_num = 1

                self.write_num(self.current_num - 1, self.current_dp)

    # Callback for Mode button
    def mode_button_callback(self, pin):
        if self._debounce(self.mode_button):
            self.toggle_led(self.red_led)

    # Callback for Incr Button
    def incr_button_callback(self, pin):
        if self._debounce(self.incr_button):
            self.increment_num()

    # Callback for Decr button
    def decr_button_callback(self, pin):
        if self._debounce(self.decr_button):
            self.decrement_num()
    
    # Callback for clock after calling start_clock24
    def clock_timer_callback(self, tim):
        self._update_clock24()

    # Callback for other timer uses
    def timer_callback(self, tim):
        self.increment_num()

    # Read hours, minutes, and seconds from rtc and and write to the display
    def _update_clock24(self):
        current_time = self.rtc.datetime()

        hours = current_time[4]
        minutes = current_time[5]
        seconds = current_time[6]

        time_str = ''

        if hours < 10:
            time_str += '0'
        time_str += str(hours)

        if minutes < 10:
            time_str += '0'
        time_str += str(minutes)

        if seconds < 10:
            time_str += '0'
        time_str += str(seconds)

        self.write_num(int(time_str), 0b010100)

    # Send commands to MAX7219
    def _register(self, command, data):
        self._cs.value(0)
        self._spi.write(bytearray([command, data]))
        self._cs.value(1)

    # Debounce function for debouncing buttons
    @staticmethod
    def _debounce(button):
        flag = 0

        for i in range(_DEBOUNCE_SAMPLES):
            flag = button.value()
            if button.value():
                return not flag

        return not flag
