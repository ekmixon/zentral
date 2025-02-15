# Event stores configuration section

Zentral events are stored using instances of the event store backends. Multiple stores can be used at the same time. Some configuration options are common to all the store backends, and some are specific to each backend.

To define a store, a backend configuration needs to be added to the base.json `stores` dictionary. A unique identifier is used as the key, and the configuration is a dictionary. For example:

```json
{
    …
    "stores": {
        "elasticseach": {
            "backend": "zentral.core.stores.backends.elasticsearch"
            …
        }
    }
}
```

## Common backend options

### `backend`

**MANDATORY**

The python module implementing the store, as a string. Currently available:

* `zentral.core.stores.backends.azure_log_analytics`
* `zentral.core.stores.backends.datadog`
* `zentral.core.stores.backends.elasticsearch`
* `zentral.core.stores.backends.http`
* `zentral.core.stores.backends.humio`
* `zentral.core.stores.backends.kinesis`
* `zentral.core.stores.backends.splunk`
* `zentral.core.stores.backends.syslog`

### `frontend`

**OPTIONAL**

A boolean indicating if the store is the main event store to be used to fetch events in the Zentral UI. Only one store can be set as the `frontend` store, and ATM, only the `datadog` and `elasticsearch` backend support fetching events for display in the UI.

### `excluded_event_types`

**OPTIONAL**

A list of event types that will not be stored. Empty by default (i.e. no filtering). Can be used to drop some of the events.

### `included_event_types`

**OPTIONAL**

The list of events that will be stored. Empty by default (i.e. no filtering). The `excluded_event_types` has precedence other this list. Can be used in secondary event stores, to only forward a subset of the Zentral events to a different system.

### `events_url_authorized_groups`

**OPTIONAL**

A list of group names. Empty by default (i.e. all users will get the links). Can be used to display the links to the events in the store to only a subset of Zentral users, if not all users have direct access to the store.

## Splunk backend options

### `hec_url`

**MANDATORY**

The base URL of the Splunk HTTP Event Collector. For example: `https://splunk.example.com:8088`. The path to the collector endpoint **must not** be included.

### `hec_token`

**MANDATORY**

The HEC token. It is recommended to use the common Zentral configuration options to read the value from an environment variable `"{{ env:ENV_VAR_NAME }}"`, a file `"{{ file:FILE_PATH }}"`, or a GCP or AWS secret `"{{ secret:NAME_OF_THE_SECRET }}"`.

### `verify_tls`

**OPTIONAL**

A boolean value to indicate if the connection must be verified or not. Default: `true`.

### `batch_size`

**OPTIONAL**

The number of events to write in a single request. Default: `1`. A value up to `100` can be used to speed up the event storage.

### `source`

**OPTIONAL**

The name of the source to use in the Splunk events.

### `index`

**OPTIONAL**

The name of the Splunk index.

### `search_app_url`

**OPTIONAL**

The URL to the Splunk search app. For example: `https://splunk.example.com/en-US/app/search/search`. Empty by default. If set, links will be displayed in the Zentral UI to allow users to see the events in Splunk.

### `computer_name_as_host_sources`

**OPTIONAL**

A list of inventory source names to use to find a hostname to set as the `host` value in the Splunk event. Empty by default (i.e. the machine serial number will be used as the `host` value).

### `serial_number_field`

**OPTIONAL**

The name of the Splunk event field to use for the machine serial number. Default: `machine_serial_number`.

### Full example

```json
{
    "backend": "zentral.core.stores.backends.splunk",
    "frontend": false,
    "hec_url": "https://splunk.example.com:8088",
    "hec_token": "{{ env:HEC_TOKEN }}",
    "batch_size": 100,
    "source": "Zentral",
    "index": "zentral",
    "search_app_url": "https://splunk.example.com/en-US/app/search/search",
    "verify_tls": true,
    "computer_name_as_host_sources": ["santa", "osquery"],
    "serial_number_field": "serial_number"
}
```

## HTTP backend options

### `endpoint_url`

**MANDATORY**

The URL where the Zentral events will be POSTed.

For example: `https://acme.service-now.com/api/now/import/zentral_events`.

### `username`

**OPTIONAL**

Username used for Basic Authentication. If used, `password` **MUST** be set too.

### `password`

**OPTIONAL**

Password used for Basic Authentication. If used, `username` **MUST** be set too.

### `headers`

**OPTIONAL**

A string / string dictionary of extra headers to be set for the HTTP requests. The `Content-Type` header is set to `application/json` by default.

**WARNING** Basic Authentication via `username` and `password` conflicts with the configuration of the `Authorization` header.

### `concurrency`

**OPTIONAL**

**WARNING** only works if the AWS SNS/SQS queues backend is used.

An integer between 1 and 20, 1 by default. The number of threads to use when posting the events. This can increase the throughput of the store worker.

### Full example

```json
{
    "backend": "zentral.core.stores.backends.http",
    "endpoint_url": "https://acme.service-now.com/api/now/import/zentral_events",
    "username": "Zentral",
    "password": "{{ env:SERVICE_NOW_API_PASSWORD }}",
    "verify_tls": true,
    "included_event_types": [
      "add_machine",
      "add_machine_os_version",
      "remove_machine_os_version",
      "add_machine_system_info",
      "remove_machine_system_info",
      "add_machine_business_unit",
      "remove_machine_business_unit",
      "add_machine_group",
      "remove_machine_group",
      "add_machine_disk",
      "remove_machine_disk",
      "add_machine_network_interface",
      "remove_machine_network_interface",
      "add_machine_osx_app_instance",
      "remove_machine_osx_app_instance",
      "add_machine_deb_package",
      "remove_machine_deb_package",
      "add_machine_program_instance",
      "remove_machine_program_instance",
      "add_machine_principal_user",
      "remove_machine_principal_user"
    ]
}
```
