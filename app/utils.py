# utils.py
from urllib.parse import urlparse
import requests
import sentry_sdk

def make_request(method, url):
    span = sentry_sdk.start_span(
        op="http.client",
        name="%s %s" % (method, url),
    )
    span.set_data("http.request.method", method)
    parsed_url = urlparse(url)
    span.set_data("url", url)
    span.set_data("server.address", parsed_url.hostname)
    span.set_data("server.port", parsed_url.port)
    response = requests.request(method=method, url=url)
    span.set_data("http.response.status_code", response.status_code)
    span.set_data("http.response_content_length", response.headers["content-length"])
    span.finish()
    return response