import arrow
import boto3
import json
import os
import requests
from ics import Calendar

def get_calendar(url):
    resp = requests.get(url)
    resp.raise_for_status()
    return Calendar(resp.text)

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

def make_geojson_feature(event):
    best_geocode = get_first_geocode_entry(event.location)
    if best_geocode:
        geometry = best_geocode['geometry']
    else:
        geometry = None

    properties = {
        'begin': event.begin.isoformat(),
        'end': event.end.isoformat(),
        'name': event.name,
        'description': event.description,
    }

    feature = {
        'type': "Feature",
        'properties': properties,
        'geometry': geometry,
    }

    return feature

def main():
    now = arrow.utcnow()
    geo_features = []

    c = get_calendar('https://calendar.google.com/calendar/ical/resistanceupdates%40gmail.com/public/basic.ics')
    # Filter out events that have already ended, sort by event begin time
    events = sorted(
        (e for e in c.events if e.end >= now),
        key=lambda e: e.begin
    )

    for e in events:
        geo_features.append(make_geojson_feature(e))

    feature_collection = {
        'type': "FeatureCollection",
        'features': geo_features,
    }

    which_bucket = os.environ.get('AWS_S3_BUCKET')
    s3 = boto3.resource('s3')
    s3.Object(which_bucket, 'events.geojson').put(
        Body=json.dumps(feature_collection, separators=(',', ':')),
        ACL='public-read',
        ContentType='application/json',
    )

if __name__ == '__main__':
    main()
