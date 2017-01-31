import arrow
import boto3
import json
import os
import re
import requests
from ics import Calendar, Event

def json_handler(obj):
    if isinstance(obj, arrow.Arrow):
        return obj.isoformat()
    else:
        return json.JSONEncoder().default(obj)

def request_geocode(addr_string):
    api_key = os.environ.get('MAPZEN_API_KEY')
    resp = requests.get(
        'https://search.mapzen.com/v1/search',
        params={
            'text': addr_string,
            'api_key': api_key,
        }
    )
    resp.raise_for_status()
    return resp.json()

def get_first_geocode_entry(addr_string):
    results = request_geocode(addr_string)
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
    match = re.match(r'.*facebook.com/events/(\d+)/?', url)
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
        'end': arrow.get(event.get('end_time')),
        'name': event.get('name'),
        'description': event.get('description'),
    }

    geometry = None
    if event.get('place'):
        geometry = {
            'type': "Point",
            'coordinates': [
                event.get('place').get('location').get('longitude'),
                event.get('place').get('location').get('latitude'),
            ]
        }

    feature = {
        'type': "Feature",
        'properties': properties,
        'geometry': geometry
    }

    # Caller expects a list of features
    return [feature]

url_action_mapping = [
    (re.compile(r'^https://calendar.google.com/calendar/ical/.*'), get_google_ical_events),
    (re.compile(r'^https://www.facebook.com/events/.*'), get_facebook_events),
]

def get_merged_events():
    resp = requests.get(os.environ.get('CALENDARS_LIST_URL'))
    resp.raise_for_status()

    events = []
    for url in resp.text.splitlines():
        for regexp, fn in url_action_mapping:
            if regexp.match(url):
                events.extend(fn(url))

    return events

def main():
    now = arrow.utcnow()
    geo_features = []

    events = get_merged_events()

    # Filter out events that have already ended, sort by event begin time
    events = sorted(
        (e for e in events if e['properties']['end'] >= now),
        key=lambda e: e['properties']['begin']
    )

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
