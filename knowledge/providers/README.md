# Provider knowledge

This directory is generated/maintained by MultiPlay.

Expected layout:

    <provider>/
      endpoints.json
      status.json
      runs/

endpoints.json is the durable interface between protocol discovery and later demo/live
validation.

Provider-specific historical observations belong in knowledge/legacy until they are
revalidated and promoted through an actual MultiPlay analysis run.
