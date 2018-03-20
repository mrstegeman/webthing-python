from queue import Queue
import json
import re
import time
import tornado.httpclient
import tornado.websocket
import websocket

from webthing.utils import get_ip


_TIME_REGEX = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$'


def http_request(method, path, data=None):
    url = 'http://127.0.0.1:8888' + path

    client = tornado.httpclient.HTTPClient()

    if data is None:
        request = tornado.httpclient.HTTPRequest(
            url,
            method=method,
            headers={
                'Accept': 'application/json',
            },
        )
    else:
        request = tornado.httpclient.HTTPRequest(
            url,
            method=method,
            headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            body=json.dumps(data),
        )

    response = client.fetch(request, raise_error=False)

    if response.body:
        return response.code, json.loads(response.body)
    else:
        return response.code, None


def run_client():
    # Test thing description
    code, body = http_request('GET', '/')
    assert code == 200
    assert body['name'] == 'My Lamp'
    assert body['type'] == 'thing'
    assert body['description'] == 'A web connected lamp'
    assert body['properties']['on']['type'] == 'boolean'
    assert body['properties']['on']['description'] == 'Whether the lamp is turned on'
    assert body['properties']['on']['href'] == '/properties/on'
    assert body['properties']['level']['type'] == 'number'
    assert body['properties']['level']['description'] == 'The level of light from 0-100'
    assert body['properties']['level']['minimum'] == 0
    assert body['properties']['level']['maximum'] == 100
    assert body['properties']['level']['href'] == '/properties/level'
    assert body['actions']['fade']['description'] == 'Fade the lamp to a given level'
    assert body['actions']['fade']['input']['type'] == 'object'
    assert body['actions']['fade']['input']['properties']['level']['type'] == 'number'
    assert body['actions']['fade']['input']['properties']['level']['minimum'] == 0
    assert body['actions']['fade']['input']['properties']['level']['maximum'] == 100
    assert body['actions']['fade']['input']['properties']['duration']['type'] == 'number'
    assert body['actions']['fade']['input']['properties']['duration']['unit'] == 'milliseconds'
    assert body['actions']['fade']['href'] == '/actions/fade'
    assert body['events']['overheated']['type'] == 'number'
    assert body['events']['overheated']['unit'] == 'celcius'
    assert body['events']['overheated']['description'] == 'The lamp has exceeded its safe operating temperature'
    assert body['events']['overheated']['href'] == '/events/overheated'
    assert len(body['links']) == 4
    assert body['links'][0]['rel'] == 'properties'
    assert body['links'][0]['href'] == '/properties'
    assert body['links'][1]['rel'] == 'actions'
    assert body['links'][1]['href'] == '/actions'
    assert body['links'][2]['rel'] == 'events'
    assert body['links'][2]['href'] == '/events'
    assert body['links'][3]['rel'] == 'alternate'
    assert body['links'][3]['href'] == 'ws://{}:8888/'.format(get_ip())

    # Test properties
    code, body = http_request('GET', '/properties/level')
    assert code == 200
    assert body['level'] == 50

    code, body = http_request('PUT', '/properties/level', {'level': 25})
    assert code == 200
    assert body['level'] == 25

    code, body = http_request('GET', '/properties/level')
    assert code == 200
    assert body['level'] == 25

    # Test events
    code, body = http_request('GET', '/events')
    assert code == 200
    assert len(body) == 0

    # Test actions
    code, body = http_request('GET', '/actions')
    assert code == 200
    assert len(body) == 0

    code, body = http_request(
        'POST',
        '/actions',
        {
            'fade': {
                'input': {
                    'level': 50,
                    'duration': 2000,
                },
            },
        })
    assert code == 201
    assert body['fade']['input']['level'] == 50
    assert body['fade']['input']['duration'] == 2000
    assert body['fade']['href'].startswith('/actions/fade/')
    assert body['fade']['status'] == 'created'
    action_id = body['fade']['href'].split('/')[-1]
    time.sleep(2.5)

    code, body = http_request('GET', '/actions')
    assert code == 200
    assert len(body) == 1
    assert len(body[0].keys()) == 1
    assert body[0]['fade']['input']['level'] == 50
    assert body[0]['fade']['input']['duration'] == 2000
    assert body[0]['fade']['href'] == '/actions/fade/' + action_id
    assert re.match(_TIME_REGEX, body[0]['fade']['timeRequested']) is not None
    assert re.match(_TIME_REGEX, body[0]['fade']['timeCompleted']) is not None
    assert body[0]['fade']['status'] == 'completed'

    code, body = http_request('DELETE', '/actions/fade/' + action_id)
    assert code == 204
    assert body is None

    # The action above generates an event, so check it.
    code, body = http_request('GET', '/events')
    assert code == 200
    assert len(body) == 1
    assert len(body[0].keys()) == 1
    assert body[0]['overheated']['data'] == 102
    assert re.match(_TIME_REGEX, body[0]['overheated']['timestamp']) is not None

    # Set up a websocket
    ws = websocket.WebSocket()
    ws.connect('ws://127.0.0.1:8888/')

    # Test setting property through websocket
    ws.send(json.dumps({
        'messageType': 'setProperty',
        'data': {
            'level': 10,
        }
    }))
    message = json.loads(ws.recv())
    assert message['messageType'] == 'propertyStatus'
    assert message['data']['level'] == 10

    code, body = http_request('GET', '/properties/level')
    assert code == 200
    assert body['level'] == 10

    # Test requesting action through websocket
    ws.send(json.dumps({
        'messageType': 'requestAction',
        'data': {
            'fade': {
                'input': {
                    'level': 90,
                    'duration': 1000,
                },
            },
        }
    }))
    message = json.loads(ws.recv())
    assert message['messageType'] == 'actionStatus'
    assert message['data']['fade']['input']['level'] == 90
    assert message['data']['fade']['input']['duration'] == 1000
    assert message['data']['fade']['href'].startswith('/actions/fade/')
    assert message['data']['fade']['status'] == 'created'
    message = json.loads(ws.recv())
    assert message['messageType'] == 'actionStatus'
    assert message['data']['fade']['input']['level'] == 90
    assert message['data']['fade']['input']['duration'] == 1000
    assert message['data']['fade']['href'].startswith('/actions/fade/')
    assert message['data']['fade']['status'] == 'pending'
    message = json.loads(ws.recv())
    assert message['messageType'] == 'propertyStatus'
    assert message['data']['level'] == 90
    message = json.loads(ws.recv())
    assert message['messageType'] == 'actionStatus'
    assert message['data']['fade']['input']['level'] == 90
    assert message['data']['fade']['input']['duration'] == 1000
    assert message['data']['fade']['href'].startswith('/actions/fade/')
    assert message['data']['fade']['status'] == 'completed'
    action_id = message['data']['fade']['href'].split('/')[-1]

    code, body = http_request('GET', '/actions')
    assert code == 200
    assert len(body) == 2
    assert len(body[1].keys()) == 1
    assert body[1]['fade']['input']['level'] == 90
    assert body[1]['fade']['input']['duration'] == 1000
    assert body[1]['fade']['href'] == '/actions/fade/' + action_id
    assert re.match(_TIME_REGEX, body[1]['fade']['timeRequested']) is not None
    assert re.match(_TIME_REGEX, body[1]['fade']['timeCompleted']) is not None
    assert body[1]['fade']['status'] == 'completed'

    code, body = http_request('GET', '/actions/fade/' + action_id)
    assert code == 200
    assert len(body.keys()) == 1
    assert body['fade']['href'] == '/actions/fade/' + action_id
    assert re.match(_TIME_REGEX, body['fade']['timeRequested']) is not None
    assert re.match(_TIME_REGEX, body['fade']['timeCompleted']) is not None
    assert body['fade']['status'] == 'completed'

    code, body = http_request('GET', '/events')
    assert code == 200
    assert len(body) == 2
    assert len(body[1].keys()) == 1
    assert body[1]['overheated']['data'] == 102
    assert re.match(_TIME_REGEX, body[1]['overheated']['timestamp']) is not None

    # Test event subscription through websocket
    ws.send(json.dumps({
        'messageType': 'addEventSubscription',
        'data': {
            'overheated': {},
        }
    }))
    ws.send(json.dumps({
        'messageType': 'requestAction',
        'data': {
            'fade': {
                'input': {
                    'level': 100,
                    'duration': 500,
                },
            },
        }
    }))
    message = json.loads(ws.recv())
    assert message['messageType'] == 'actionStatus'
    assert message['data']['fade']['input']['level'] == 100
    assert message['data']['fade']['input']['duration'] == 500
    assert message['data']['fade']['href'].startswith('/actions/fade/')
    assert message['data']['fade']['status'] == 'created'
    assert re.match(_TIME_REGEX, message['data']['fade']['timeRequested']) is not None
    message = json.loads(ws.recv())
    assert message['messageType'] == 'actionStatus'
    assert message['data']['fade']['input']['level'] == 100
    assert message['data']['fade']['input']['duration'] == 500
    assert message['data']['fade']['href'].startswith('/actions/fade/')
    assert message['data']['fade']['status'] == 'pending'
    assert re.match(_TIME_REGEX, message['data']['fade']['timeRequested']) is not None
    message = json.loads(ws.recv())
    assert message['messageType'] == 'propertyStatus'
    assert message['data']['level'] == 100
    message = json.loads(ws.recv())
    assert message['messageType'] == 'event'
    assert message['data']['overheated']['data'] == 102
    assert re.match(_TIME_REGEX, message['data']['overheated']['timestamp']) is not None
    message = json.loads(ws.recv())
    assert message['messageType'] == 'actionStatus'
    assert message['data']['fade']['input']['level'] == 100
    assert message['data']['fade']['input']['duration'] == 500
    assert message['data']['fade']['href'].startswith('/actions/fade/')
    assert message['data']['fade']['status'] == 'completed'
    assert re.match(_TIME_REGEX, message['data']['fade']['timeRequested']) is not None
    assert re.match(_TIME_REGEX, message['data']['fade']['timeCompleted']) is not None

    ws.close()


if __name__ == '__main__':
    exit(run_client())