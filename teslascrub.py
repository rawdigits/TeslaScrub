"""
  _______        _        _____                 _
 |__   __|      | |      / ____|               | |
    | | ___  ___| | __ _| (___   ___ _ __ _   _| |__
    | |/ _ \/ __| |/ _` |\___ \ / __| '__| | | | '_ \
    | |  __/\__ \ | (_| |____) | (__| |  | |_| | |_) |
    |_|\___||___/_|\__,_|_____/ \___|_|   \__,_|_.__/

            Where is my Model 3, Elon?
"""
import os
import paho.mqtt.client as paho
import re
import time
import logging
import requests
import json

from logging.handlers import RotatingFileHandler
from urllib.parse import urlparse
from configparser import ConfigParser
from bs4 import BeautifulSoup

log = logging.getLogger()
BASE_PATH = os.path.dirname(os.path.realpath(__file__))

config = ConfigParser()
config.read(f'{BASE_PATH}/config.ini')

mqtt_broker=config['MQTT']['BROKER_IP']
mqtt_port=config.getint('MQTT', 'BROKER_PORT')
mqtt_topic="reservations/blah"
def on_publish(client,userdata,result):             #create function for callback
    print("MQTT published")
    pass
client1= paho.Client("control1")                           #create client object
client1.on_publish = on_publish                          #assign function to callback
client1.connect(mqtt_broker,mqtt_port)                                 #establish connection
ret= client1.publish(mqtt_topic,"on")                   #publish

def setup_logging():
    LOG_PATH = "{}/{}.log".format(BASE_PATH,
                                  os.path.basename(__file__).replace(".py", ""))

    if config.getboolean('Internal', 'Debug'):
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.INFO)
    formatter = logging.Formatter('[ %(asctime)s ] [ %(levelname)5s ] [ %(name)s.%(funcName)s:%(lineno)s ] %(message)s')
    handler = RotatingFileHandler(LOG_PATH, maxBytes=5 * 1024 ** 2, backupCount=5)
    handler.setFormatter(formatter)
    log.addHandler(handler)

    # Quiet down requests lib as it prints private info
    logging.getLogger("requests.packages.urllib3").setLevel(logging.INFO)

class ScrubbingError(Exception):
    pass

class ProfileScrubber():
    def __init__(self,  tesla_username, tesla_password):
        self.session = requests.Session()
        self.tesla_username = tesla_username
        self.tesla_password = tesla_password
        self.__reservation_numbers = []
        self.log = logging.getLogger(str(self))
        self.LOGIN_URL = str(config['Tesla']['LOGIN_URL'])
        self.CAR_URL = str(config['Tesla']['CAR_URL'])
        self.RESERVATION_NUMBER = str(config['Tesla']['RESERVATION_NUMBER'])

    def __repr__(self):
        return "TeslaProfileScrubber"

    def get_csrf_token(self):
        login_page = self.session.get(self.LOGIN_URL)
        login_page.raise_for_status()

        self.log.debug(f"Login page contents: {login_page.text.encode('utf-8')}")

        login_page = BeautifulSoup(login_page.text, "html.parser")
        self.log.info(f"Loaded Tesla login page from {self.LOGIN_URL}")

        self.csrf_token = ""
        try:
            self.csrf_token = login_page.find('input', {'name':'_csrf'}).get('value')
        except AttributeError:
            pass

        if not self.csrf_token:
            self.error("Could not find CSRF token in login page.")

        self.log.info(f"Found CSRF token.")
        self.log.debug(f"CSRF token value: {self.csrf_token}")

    def log_in(self):
        data = {
            "user": '',
            "_csrf": self.csrf_token,
            'email': self.tesla_username,
            'password': self.tesla_password
        }

        self.headers = {
            'Origin': "{}://{}".format(*urlparse(self.LOGIN_URL)[0:2]),
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/66.0.3359.117 Safari/537.36',
            'Referer': self.LOGIN_URL
        }
        resp = self.session.post(self.LOGIN_URL, data=data, headers=self.headers)
        resp.raise_for_status()
        self.profile_page = resp.text

        if not self.profile_page:
            self.error("Profile page failed to load.")


        self.log.info(f"Loaded Tesla profile page from {self.LOGIN_URL}")
        self.log.debug(f"Profile page contents: {self.profile_page.encode('utf-8')}")

    def error(self, message):
        self.log.error(message)
        raise ScrubbingError(message)

    def find_reservation_numbers(self):
        complete_url = self.CAR_URL+self.RESERVATION_NUMBER
        self.log.info(f"Loaded Tesla profile page from {complete_url}")
        resp = self.session.get(complete_url, headers=self.headers)
        resp.raise_for_status()
        self.profile_page = resp.text
        self.log.debug(f"Profile page contents: {self.profile_page.encode('utf-8')}")

        if not self.profile_page:
            self.error("Profile page failed to load.")

        account_page = BeautifulSoup(self.profile_page, "html.parser")

        vin_re = re.compile(r'5YJ\w+')
        #vin_re = re.compile(r'RN\w+')
        vins = vin_re.findall(account_page.get_text())
        if len(vins) > 0:
            unique_vins = set(vins)
            self.log.info(unique_vins)
            ret= client1.publish("reservations/VIN"," ".join(unique_vins))                   #publish
            ret= client1.publish("reservations/have_vin","ON")                   #publish
        else:
            ret= client1.publish("reservations/VIN", "NO VIN")
            ret= client1.publish("reservations/have_vin","OFF")                   #publish

        delivery_re = re.compile(r'Estimated delivery: \w+')
        deliveries = delivery_re.findall(account_page.get_text())
        if len(deliveries) > 0:
            self.log.info(deliveries)
            ret= client1.publish("reservations/delivery"," ".join(deliveries))                   #publish
            ret= client1.publish("reservations/have_delivery","ON")                   #publish
        else:
            ret= client1.publish("reservations/delivery","NO DELIVERY DATE")                   #publish
            ret= client1.publish("reservations/have_delivery","OFF")                   #publish

        canary_re = re.compile(r'isNotMatchedToRa00Vin')
        canary = canary_re.findall(account_page.get_text())
        if len(canary) > 0:
            ret= client1.publish("reservations/canary","ON")                   #publish
        else:
            ret= client1.publish("reservations/canary","OFF")                   #publish

    def scrub(self):
        self.get_csrf_token()
        self.log_in()
        while True:
            try:
                self.find_reservation_numbers()
            except:
                log.info("It failed that time, but let's be dumb and just keep trying.")
            time.sleep(30)

if __name__ == "__main__":
    setup_logging()

    log.info("Starting Tesla profile scrubber...")
    scrubber = ProfileScrubber(tesla_username=config['Tesla']['USERNAME'],
                               tesla_password=config['Tesla']['PASSWORD'])
    try:
        scrubber.scrub()
    except ScrubbingError as error:
        log.debug("Error while scrubbing:", exc_info=error)

    log.info("Exiting Tesla profile scrubber...")
