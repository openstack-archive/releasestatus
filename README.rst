ReleaseStatus page generator
============================

The releasestatus.py script is used to extract data from Launchpad
and Gerrit and produce static HTML that shows where we are in the
current release cycle.

Prerequisites
-------------

You'll need the following Python modules installed:
 - launchpadlib
 - jinja2
 - yaml

You'll also need a valid SSH key for accessing Gerrit via SSH
installed in ~/.gerritssh/id_rsa.

Usage
-----

python releasestatus.py grizzly.yaml > static/index.html

It may take a few minutes to run, depending on the number of
projects and how many blueprints they contain.

Configuration
-------------

The YAML configuration file describes the series and projects
you want to generate data for. See comments in the example file
releasestatus.yaml.sample for details.
