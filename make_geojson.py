import arrow
import boto3
import json
import os
import re
import requests
import sys
from ics import Calendar

import logging
logger = logging.getLogger('app')
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.DEBUG)
logger.addHandler(ch)

def json_handler(obj):
    if isinstance(obj, arrow.Arrow):
        return obj.isoformat()
    else:
        return json.JSONEncoder().default(obj)

def request_geocode(addr):
    api_key = os.environ.get('MAPZEN_API_KEY')

    if isinstance(addr, dict):
        params = dict(api_key=api_key, **addr)
        resp = requests.get(
            'https://search.mapzen.com/v1/search/structured',
            params=params,
        )
    else:
        resp = requests.get(
            'https://search.mapzen.com/v1/search',
            params={
                'text': addr,
                'api_key': api_key,
            }
        )
    resp.raise_for_status()
    return resp.json()

def get_first_geocode_entry(addr):
    if not addr:
        return None

    results = request_geocode(addr)
    features = results.get('features')
    return features[0] if features else None

def convert_ical_event_to_geojson(event):
    best_geocode = get_first_geocode_entry(event.location)
    if best_geocode:
        geometry = best_geocode['geometry']
    else:
        geometry = None

    properties = {
        'begin': event.begin,
        'end': event.end,
        'name': event.name,
        'description': event.description,
    }

    feature = {
        'type': "Feature",
        'properties': properties,
        'geometry': geometry,
    }

    return feature

def get_google_ical_events(url):
    resp = requests.get(url)
    resp.raise_for_status()
    events = Calendar(resp.text).events

    return [convert_ical_event_to_geojson(e) for e in events]

def get_facebook_events(url):
    # The URL we get will probably be a Facebook web URL, so extract the event ID from it
    match = re.match(r'.*facebook.com/events/(\d+)/?.*', url)
    event_id = match.group(1)

    # You can use `app_id|app_secret` as the access_token
    # to avoid programmatically requesting one:
    # https://developers.facebook.com/docs/facebook-login/access-tokens/#apptokens
    merged_fb_tokens = '|'.join([
        os.environ.get('FACEBOOK_APP_ID'),
        os.environ.get('FACEBOOK_APP_SECRET')
    ])
    resp = requests.get(
        'https://graph.facebook.com/v2.8/{}'.format(event_id),
        params=dict(
            format='json',
            access_token=merged_fb_tokens,
        )
    )
    resp.raise_for_status()

    event = resp.json()

    properties = {
        'begin': arrow.get(event.get('start_time')),
        'name': event.get('name'),
        'description': event.get('description'),
    }

    if event.get('end_time'):
        properties['end'] = arrow.get(event.get('end_time'))
    else:
        # If there's no end time, set end to begin?
        properties['end'] = properties['begin']

    geometry = None
    place = event.get('place')
    if place:
        location = place.get('location')
        if location:
            geometry = {
                'type': "Point",
                'coordinates': [
                    location.get('longitude'),
                    location.get('latitude'),
                ]
            }
        else:
            best_geocode = get_first_geocode_entry(place.get('name'))
            if best_geocode:
                geometry = best_geocode['geometry']

    feature = {
        'type': "Feature",
        'properties': properties,
        'geometry': geometry
    }

    # Caller expects a list of features
    return [feature]

def get_townhall_events(url):
    import csv

    townhall_tz_mapping = {
        'EST': 'UTC-05:00',
        'CST': 'UTC-06:00',
        'MST': 'UTC-07:00',
        'PST': 'UTC-08:00',
    }

    resp = requests.get(url)
    resp.raise_for_status()
    body = resp.text.encode('utf-8')
    lines = body.splitlines()
    # Chop off the header rows
    lines = lines[10:]
    lines = csv.DictReader(lines)
    features = []
    for line in lines:
        time_text = ' '.join(filter(None, [
            line.get('Date'),
            line.get('Time'),
            townhall_tz_mapping.get(line.get('Time Zone')),
        ]))
        try:
            time = arrow.get(time_text, 'dddd, MMMM D, YYYY H:mm A Z')
        except Exception, e:
            print "Failed to parse '{}': {}".format(time_text, e.message)
            continue

        properties = {
            'begin': time,
            'end': time,
            'name': "{Member} {Meeting Type}".format(**line),
            'description': "{Member} ({Party}) {Meeting Type} for {State} {District}".format(**line),
        }

        if not line.get('Street Address'):
            continue

        best_geocode = get_first_geocode_entry({
            'address': line.get('Street Address'),
            'locality': line.get('City'),
            'region': line.get('State'),
            'postalcode': line.get('Zip'),
        })
        if best_geocode:
            geometry = best_geocode['geometry']
        else:
            geometry = None

        feature = {
            'type': "Feature",
            'properties': properties,
            'geometry': geometry
        }
        features.append(feature)

    return features

url_action_mapping = [
    (re.compile(r'^https://calendar.google.com/calendar/ical/.*'), get_google_ical_events),
    (re.compile(r'^http://live-timely-.*.time.ly/\.*'), get_google_ical_events),
    (re.compile(r'^https://www.facebook.com/events/.*'), get_facebook_events),
    (re.compile(r'^https://docs.google.com/spreadsheet/ccc\?key=1yq1NT9DZ2z3B8ixhid894e77u9rN5XIgOwWtTW72IYA&output=csv$'), get_townhall_events),
]

def get_merged_events():
    # resp = requests.get(os.environ.get('CALENDARS_LIST_URL'))
    # resp.raise_for_status()
    # urls = resp.text.splitlines()
    urls = open('calendars.txt', 'r').read().splitlines()

    now = arrow.utcnow()

    events = []
    for url in urls:
        this_url_events = None
        for regexp, fn in url_action_mapping:
            if regexp.match(url):
                try:
                    this_url_events = [
                        e for e in fn(url) if e['properties']['end'] >= now
                    ]
                except:
                    logger.exception("Problem occured while fetching events")

                if this_url_events:
                    events.extend(this_url_events)
                    logger.info("Calendar %s added %s events", url, len(this_url_events))
                else:
                    logger.warn("Calendar %s had no events in the future", url)
                break

        if this_url_events is None:
            logger.warn("Calendar %s could not be processed", url)

    return events

def main():
    events = get_merged_events()

    # Filter out events that have already ended, sort by event begin time
    events = sorted(events, key=lambda e: e['properties']['begin'])

    feature_collection = {
        'type': "FeatureCollection",
        'features': events,
    }

    which_bucket = os.environ.get('AWS_S3_BUCKET')
    s3 = boto3.resource('s3')
    s3.Object(which_bucket, 'events.geojson').put(
        Body=json.dumps(
            feature_collection,
            separators=(',', ':'),
            default=json_handler,
        ),
        ACL='public-read',
        ContentType='application/json',
    )

if __name__ == '__main__':
    main()
