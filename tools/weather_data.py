#!/usr/bin/env python3
"""Direct port of the PHP fetchWeatherData() method.

Behaviour matches the original: same URL construction, same disabled TLS
verification, prints the URL and the decoded payload, and returns the raw
response body (or False on error). The API key is passed in as a parameter.
"""

import json
import ssl
import sys
import urllib.error
import urllib.request


def fetch_weather_data(locatie, datum, api_key):
    """Haal de weerdata op van de API.

    :param locatie: location query (lat,lon or place name)
    :param datum: date as YYYY-MM-DD
    :param api_key: WeatherAPI key
    :return: raw response body as str, or False on error
    """
    url = f"https://api.weatherapi.com/v1/history.json?q={locatie}&dt={datum}&key={api_key}"
    print(f"{url}")

    # CURLOPT_SSL_VERIFYPEER = false / CURLOPT_SSL_VERIFYHOST = 0
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    request = urllib.request.Request(url, headers={"accept": "application/json"})

    try:
        with urllib.request.urlopen(request, context=context) as handle:
            response = handle.read().decode("utf-8")
    except urllib.error.URLError as exc:
        print(f"cURL Error: {exc}")
        return False

    # JSON netjes weergeven
    try:
        data = json.loads(response)
        print(json.dumps(data, indent=4, ensure_ascii=False))
    except json.JSONDecodeError as exc:
        print(f"JSON Error: {exc}")

    return response


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(f"usage: {sys.argv[0]} <locatie> <datum> <api_key>")
        sys.exit(1)
    fetch_weather_data(sys.argv[1], sys.argv[2], sys.argv[3])
