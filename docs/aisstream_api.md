# AISStream API Documentation

## Overview
AISStream.io provides a continuous real-time stream of maritime data via **WebSockets**. It delivers vessel positions, directions, status, and static data using the AIS (Automatic Identification System) protocol, formatted in JSON.

## Authentication
To connect to the service, an API Key is required.
1. Sign in via [aisstream.io/authenticate](https://aisstream.io/authenticate).
2. Generate an API key from the [API Keys page](https://aisstream.io/apikeys).

## Connection Details
- **Endpoint**: `wss://stream.aisstream.io/v0/stream`
- **Protocol**: Secure WebSockets (wss)
- **Time Limit**: A subscription message MUST be sent within **3 seconds** of opening the connection, or the server will terminate it.
- **Connection Health**: If your client cannot process messages fast enough (creating a large backlog on the TCP connection), the server will disconnect you.

## Subscription Message format
Upon connecting, send a JSON object with your configuration.

```json
{
  "APIKey": "<YOUR_API_KEY>",
  "BoundingBoxes": [[[-90, -180], [90, 180]]],
  "FiltersShipMMSI": ["368207620", "367719770"], 
  "FilterMessageTypes": ["PositionReport"]
}
```

### Parameters:
- `APIKey` (Required): Your API key string.
- `BoundingBoxes` (Required): A list of bounding boxes. Each box is defined by two corners: `[[[lat1, lon1], [lat2, lon2]]]`. E.g., `[-90, -180]` to `[90, 180]` covers the whole world.
- `FiltersShipMMSI` (Optional): An array of strings representing MMSI (Maritime Mobile Service Identity) to filter specific ships. Max 50 MMSI values.
- `FilterMessageTypes` (Optional): An array of AIS message types to filter (e.g., `"PositionReport"`, `"ShipStaticData"`).

### Updating a Subscription
To change the filter, send a new subscription JSON object through the **same open websocket connection**. It acts as a swap-and-replace operation.

## Message Format
Received messages are formatted as JSON objects.
```json
{
  "MessageType": "PositionReport",
  "MetaData": {
    "MMSI": 259000420,
    "ShipName": "AUGUSTSON",
    "latitude": 66.02695,
    "longitude": 12.2538216,
    "time_utc": "2022-12-29 18:22:32.318353 +0000 UTC"
  },
  "Message": {
    "PositionReport": {
      "UserID": 259000420,
      "Valid": true,
      "Latitude": 66.02695,
      "Longitude": 12.2538216,
      "Sog": 0,
      "Cog": 308,
      "TrueHeading": 235,
      "NavigationalStatus": 15,
      "RateOfTurn": 4,
      "Timestamp": 31
    }
  }
}
```

## Python Client Setup (using uv)

```bash
uv init
uv add websockets
```

**main.py**:
```python
import asyncio
import websockets
import json
from datetime import datetime, timezone

async def connect_ais_stream():
    async with websockets.connect("wss://stream.aisstream.io/v0/stream") as websocket:
        subscribe_message = {
            "APIKey": "<YOUR_API_KEY>",
            "BoundingBoxes": [[[-90, -180], [90, 180]]],
            "FilterMessageTypes": ["PositionReport"]
        }
        await websocket.send(json.dumps(subscribe_message))

        async for message_json in websocket:
            message = json.loads(message_json)
            if message["MessageType"] == "PositionReport":
                data = message['Message']['PositionReport']
                print(f"[{datetime.now(timezone.utc)}] MMSI: {data['UserID']} - Pos: {data['Latitude']}, {data['Longitude']}")

if __name__ == "__main__":
    asyncio.run(connect_ais_stream())
```
