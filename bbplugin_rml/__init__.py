"""RML-based JSON-to-RDF transform plugin for OGC Building Blocks."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from jsonpath_ng.ext import parse as parse_jsonpath
from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF

RR = Namespace("http://www.w3.org/ns/r2rml#")
RML = Namespace("http://semweb.mmlab.be/ns/rml#")
QL = Namespace("http://semweb.mmlab.be/ns/ql#")
XSD = Namespace("http://www.w3.org/2001/XMLSchema#")

_TEMPLATE = re.compile(r"\{([^{}]+)\}")


@dataclass
class _Row:
    value: Any
    root: Any


def _mapping_graph(mapping: str) -> Graph:
    # Some older RML examples use rdfs terms without declaring the prefix.
    if "rdfs:" in mapping and "@prefix rdfs:" not in mapping:
        mapping = "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>.\n" + mapping
    graph = Graph()
    graph.parse(data=mapping, format="turtle")
    return graph


def _path_value(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)] if int(part) < len(current) else None
        else:
            return None
    return current


def _reference(row: _Row, reference: str) -> Any:
    if reference.startswith("$"):
        matches = parse_jsonpath(reference).find(row.root)
        return matches[0].value if matches else None
    return _path_value(row.value, reference)


def _render(value: str, row: _Row) -> str:
    return _TEMPLATE.sub(lambda match: str(_reference(row, match.group(1)) or ""), value)


def _term(value: Any, row: _Row, datatype: URIRef | None = None) -> URIRef | Literal | BNode:
    if isinstance(value, str) and (value.startswith("http://") or value.startswith("https://")):
        term: URIRef | Literal = URIRef(value)
    elif isinstance(value, (int, float, bool)):
        term = Literal(value)
    else:
        term = Literal(value)
    if datatype is not None and isinstance(term, Literal):
        term = Literal(str(term), datatype=datatype)
    return term


def _object_term(graph: Graph, mapping: URIRef, row: _Row, parent_rows: dict[URIRef, list[_Row]]) -> list[Any]:
    constant = graph.value(mapping, RR.constant)
    if constant is not None:
        return [_term(str(constant), row)]

    reference = graph.value(mapping, RML.reference)
    datatype = graph.value(mapping, RR.datatype)
    if reference is not None:
        value = _reference(row, str(reference))
        if value is None:
            return []
        if isinstance(value, list):
            return [_term(item, row, datatype) for item in value]
        return [_term(value, row, datatype)]

    template = graph.value(mapping, RR.template)
    if template is not None:
        return [URIRef(_render(str(template), row))]

    parent_map = graph.value(mapping, RR.parentTriplesMap)
    if parent_map is not None:
        joins = list(graph.objects(mapping, RR.joinCondition))
        results = []
        for parent_row in parent_rows.get(parent_map, []):
            if all(
                _render(str(graph.value(join, RR.child)), row)
                == _render(str(graph.value(join, RR.parent)), parent_row)
                for join in joins
            ):
                results.extend(_subject_terms(graph, parent_map, parent_row))
        return results
    return []


def _subject_terms(graph: Graph, mapping: URIRef, row: _Row) -> list[Any]:
    subject_map = graph.value(mapping, RR.subjectMap)
    if subject_map is None:
        return []
    template = graph.value(subject_map, RR.template)
    if template is not None:
        return [URIRef(_render(str(template), row))]
    constant = graph.value(subject_map, RR.constant)
    if constant is not None:
        return [_term(str(constant), row)]
    return [BNode()]


def _rows(graph: Graph, mapping: URIRef, data: Any) -> list[_Row]:
    source = graph.value(mapping, RML.logicalSource)
    iterator = graph.value(source, RML.iterator) if source else None
    if iterator is None:
        return [_Row(data, data)]
    return [_Row(match.value, data) for match in parse_jsonpath(str(iterator)).find(data)]


def _serialize(graph: Graph, target: str) -> str:
    if target in {"text/turtle", "application/turtle"}:
        return graph.serialize(format="turtle")
    if target in {"application/n-triples", "application/ntriples"}:
        return graph.serialize(format="nt")
    if target == "application/ld+json":
        return graph.serialize(format="json-ld", auto_compact=True, indent=2)
    raise ValueError(f"Unsupported RML output media type: {target}")


class RmlTransformer:
    """Execute an RML mapping against JSON and return serialized RDF."""

    transform_types = ["rml"]
    default_inputs = ["application/json"]
    default_outputs = ["text/turtle"]

    def transform(self, metadata: SimpleNamespace) -> str:
        data = json.loads(metadata.input_data)
        rules = _mapping_graph(metadata.transform_content)
        graph = Graph()
        mappings = list(rules.subjects(RDF.type, RR.TriplesMap))
        rows = {mapping: _rows(rules, mapping, data) for mapping in mappings}
        subjects = {
            mapping: [row for row in rows[mapping]] for mapping in mappings
        }

        for mapping in mappings:
            for row in rows[mapping]:
                for subject in _subject_terms(rules, mapping, row):
                    subject_map = rules.value(mapping, RR.subjectMap)
                    for class_name in rules.objects(subject_map, RR.class_):
                        graph.add((subject, RDF.type, class_name))
                    for pom in rules.objects(mapping, RR.predicateObjectMap):
                        predicate = rules.value(pom, RR.predicate)
                        object_map = rules.value(pom, RR.objectMap)
                        if predicate is None or object_map is None:
                            continue
                        for obj in _object_term(rules, object_map, row, subjects):
                            graph.add((subject, predicate, obj))

        target = getattr(metadata, "target_mime_type", None) or "text/turtle"
        return _serialize(graph, target)
