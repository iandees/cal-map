# cal-map

cal-map is designed to merge together various sources of events and put them in a single GeoJSON file so that they can be mapped easily.

## Development

The preferred method of development is to use a Python virtualenv. Dependencies are specified in `requirements.txt`. To get going quickly on a Linux or Mac:

```bash
git clone git@github.com:iandees/cal-map.git
cd cal-map
virtualenv .env
source .env/bin/activate
pip install -r requirements.txt
```

## Running

The script relies on several external services that you'll need to set up beforehand:

1. Set up an S3 bucket and generate an IAM profile with permissions to write the resulting geojson file. You'll need access tokens to push to S3.
2. Set up a Mapzen API key so that events with a location but no latitude/longitude can be geocoded to be placed on the map.
3. Set up a Facebook app. Facebook's API only lets you download event information through their API using a request signed by your app's API key.

Once you've got the pre-requisites set up and the Python code installed, you can run it by specifying some configuration environment variables and running the `make_geojson.py` script:

```bash
AWS_ACCESS_KEY_ID="..." \
AWS_SECRET_ACCESS_KEY="..." \
AWS_S3_BUCKET="..." \
MAPZEN_API_KEY="..." \
FACEBOOK_APP_ID="..." \
FACEBOOK_APP_SECRET="..." \
CALENDARS_LIST_URL="..." \
python make_geojson.py
```

