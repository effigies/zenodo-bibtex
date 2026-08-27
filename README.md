# zenodo-bibtex

A utility for working around a defect in the [Zenodo REST API][] that results in an
HTTP 500 error code when requesting a set of records in BibTeX format.

[Zenodo REST API]: https://developers.zenodo.org/

## Demonstration

Attempting to retrieve a collection of records in BibTeX format fails with a 500 error:

```console
$ curl -s -o /dev/null -w '%{http_code}\n' \
    -H 'Accept: application/x-bibtex' \
    'https://zenodo.org/api/records?size=3'
500
```

The same media type works fine on a single record:

```console
$ curl -s -H 'Accept: application/x-bibtex' \
    'https://zenodo.org/api/records/3233986' | head -2
@software{the_turing_way_community_2019_3233986,
  author       = {The Turing Way Community and
```

## Approach

[Zenodo][] is built on [InvenioRDM][], which has a [BibTeX serializer][].
We can use the undocumented `application/vnd.inveniordm.v1+json` to retrieve the
internal representation of the record, and then reimplement the serialization
locally to produce BibTeX output.

[Zenodo]: https://zenodo.org/
[InvenioRDM]: https://inveniosoftware.org/products/rdm/
[BibTeX serializer]: https://github.com/Invenio/invenio-rdm-records/blob/main/invenio_rdm_records/serializers/bibtex.py

## Installation

```console
uv tool install git+https://github.com/effigies/zenodo-bibtex
```

## Usage

The CLI has two subcommands. `fetch` performs the query against Zenodo and needs
`ZENODO_TOKEN` to be defined in the environment.
I recommend using [direnv](https://direnv.net/) to load a `.envrc` file with the token,
but any method works.

```console
$ zenodo-bibtex fetch --orcid 0000-0002-6533-164X > records.json
```

`convert` does the serialization and needs neither a token nor a network connection — it is
a pure function of the JSON `fetch` produces, so a bibliography can be rebuilt entirely
offline from saved JSON:

```console
$ zenodo-bibtex convert < records.json > refs.bib
```

For what it's worth, I combine this with [bibtool][] to retrieve records for
my CV:

```console
$ zenodo-bibtex fetch --orcid $ORCID | zenodo-bibtex convert | \
    bibtool -r biblatex -r cv -s -F -f '{%-2T(title)}' -o zenodo.bib
```

[bibtool]: https://www.ctan.org/pkg/bibtool

That default output (`--wrapping=compat`) is byte-identical to what
`GET /api/records/21465761` with `Accept: application/x-bibtex` returns directly.
An experimental `--wrapping=fixed` mode aims to improve the formatting of long titles.

```console
$ uv run zenodo-bibtex fetch --query 'recid:21465761' \
  | uv run zenodo-bibtex convert --wrapping fixed
@software{oscar_esteban_2026_21465761,
  author       = {Oscar Esteban and
                  Christopher J. Markiewicz and
                  Mathias Goncalves},
  title        = {SDCflows: Susceptibility Distortion Correction
                  workFLOWS.},
  month        = jul,
  year         = 2026,
  publisher    = {Zenodo},
  version      = {2.16.0},
  doi          = {10.5281/zenodo.21465761},
  url          = {https://doi.org/10.5281/zenodo.21465761},
}
```

`--all-versions` cites the parent (concept) DOI instead of the version DOI, which also
changes the citation key:

```console
$ uv run zenodo-bibtex fetch --query 'recid:21465761' \
  | uv run zenodo-bibtex convert --all-versions
@software{oscar_esteban_2026_3234946,
  author       = {Oscar Esteban and
                  Christopher J. Markiewicz and
                  Mathias Goncalves},
  title        = {SDCflows: Susceptibility Distortion Correction
                   workFLOWS.
                  },
  month        = jul,
  year         = 2026,
  publisher    = {Zenodo},
  version      = {2.16.0},
  doi          = {10.5281/zenodo.3234946},
  url          = {https://doi.org/10.5281/zenodo.3234946},
}
```

A per-record failure is reported on stderr with the record id and does not stop the rest of
the bibliography from being emitted; `convert` then exits non-zero.

## Development

Run tests with:

```console
$ uv run --dev pytest
```

### Oracle fixtures

`tests/oracle/fixtures/` pairs each record's RDM JSON with the BibTeX Zenodo itself
returns for it, and `tests/test_oracle.py` asserts our output matches byte for byte.
Regenerating requires a token and hits the network.

## Layout

| Path                 | Purpose                                                       |
| -------------------- | ------------------------------------------------------------- |
| `repro.sh`           | Minimal reproduction of the upstream 500                      |
| `src/zenodo_bibtex/` | The CLI, list-endpoint fetching, and BibTeX serialization     |
| `tests/`             | Unit tests, plus the oracle fixture corpus in `tests/oracle/` |
| `pyproject.toml`     | Package metadata, dependencies, pytest and ruff config        |
| `tox.ini`            | Test matrix (py313, py314) and the lint environment           |

## Reference

- [Zenodo REST API](https://developers.zenodo.org/)
- [Content negotiation / representations](https://developers.zenodo.org/#representation)
- [Rate limiting](https://developers.zenodo.org/#rate-limiting)

## License

This code is released as MIT-0 (no attribution required).
The MIT-licensed https://github.com/inveniosoftware/invenio-rdm-records
was consulted extensively to generate this utility.

### LLM Disclosure

This package was developed with the use of a large language model (LLM),
and may not be copyrightable in all jurisdictions.

The code has not been audited by a human, only its outputs.
