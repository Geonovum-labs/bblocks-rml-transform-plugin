# bblocks-rml-transform-plugin

Adds an `rml` transform type to the OGC Building Blocks postprocessor. The plugin executes an RML mapping against JSON input and returns RDF.

The mapping is supplied through `metadata.transform_content`, so a building block can keep its RML in `transforms.yaml` with `ref`:

```yaml
transforms:
  - id: otlp-to-rdf
    type: rml
    ref: transforms/otel-prov.rml.ttl
    inputs:
      mediaTypes: [application/json]
    outputs:
      mediaTypes: [text/turtle]
```

Register the plugin in `bblocks-config.yaml` when installing it from a package or Git repository:

```yaml
plugins:
  transforms:
    - pip: ./rml-transform-plugin
      modules:
        - bbplugin_rml
```

The implementation supports the RML/R2RML features used by the example mapping: JSONPath logical-source iterators, references, templates, constants, classes, datatypes, and parent triples maps with join conditions. Output media types supported by the plugin are `text/turtle`, `application/n-triples`, and `application/ld+json`.

This plugin is intentionally isolated from the register sources. The existing `otel-prov.rml.ttl` can be used as the transform script via `ref`, but this package does not alter it or any existing building block.
