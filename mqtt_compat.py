import paho.mqtt.client as mqtt


def create_client(client_id: str = "") -> mqtt.Client:
    """ create mqtt client for paho-mqtt 1.x and 2.x

    paho-mqtt 2.x needs the callback api version as first parameter,
    the code uses the callbacks of version 1.x
    """
    if hasattr(mqtt, "CallbackAPIVersion"):
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id)
    return mqtt.Client(client_id)
