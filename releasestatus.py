# Copyright 2011 Thierry Carrez <thierry@openstack.org>
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from launchpadlib.launchpad import Launchpad
from datetime import date, datetime
from jinja2 import Environment, FileSystemLoader
import json
import os
import re
import subprocess
import sys
import yaml


class GerritReviews():
    def __init__(self, products):
        self.products = products
        self.under_review = self._get_from_gerrit('status:open')
        self.merged = self._get_from_gerrit('status:merged')

    def _get_from_gerrit(self, *query):
        chg = {}
        age = '2mon'
        host = "review.openstack.org"
        port = "29418"

        base_cmd = ['/usr/bin/ssh', '-p', port, host, 'gerrit', 'query',
                    '--format=JSON', 'branch:master', 'AND', 'NOT',
                    'age:%s' % age] + list(query)

        for product in self.products:
            chg[product] = []
            prod_cmd = base_cmd + ['AND', 'project:openstack/%s' % product]
            sortkey = None

            while True:
                if sortkey:
                    cmd = prod_cmd + ['AND', 'resume_sortkey:%s' % sortkey]
                else:
                    cmd = prod_cmd

                proc = subprocess.Popen(cmd, bufsize=1, stdin=None,
                                        stdout=subprocess.PIPE, stderr=None)

                end_of_changes = False
                for line in proc.stdout:
                    data = json.loads(line)
                    if 'rowCount' in data:
                        if data['rowCount'] == 0:
                            end_of_changes = True
                            break
                        else:
                            break
                    if data in chg[product]:
                        end_of_changes = True
                        break
                    sortkey = data['sortKey']
                    chg[product].append(data)
                if end_of_changes:
                    break
        return chg


class BlueprintReview():
    def __init__(self, link, image):
        self.url = link['url']
        self.subject = link['subject']
        self.image = image


class ExtendedBlueprint():
    priorities = ('Essential', 'High', 'Medium', 'Low', 'Undefined', 'Not')

    implementations = ('Implemented', 'Deployment', 'Needs Code Review',
                       'Beta Available', 'Good progress', 'Slow progress',
                       'Blocked', 'Needs Infrastructure', 'Started',
                       'Not started', 'Unknown', 'Deferred', 'Informational')

    def __init__(self, lbp):
        self.name = lbp.name
        self.pname = lbp.target.name
        self.whiteboard = lbp.whiteboard
        self.priority = lbp.priority
        self.implementation = lbp.implementation_status
        if lbp.milestone:
            self.milestonename = lbp.milestone.name
            self.milestonedate = lbp.milestone.date_targeted or '2099-12-30'
            self.milestonelink = lbp.milestone.web_link
        else:
            self.milestonename = ''
            self.milestonedate = '2099-12-31'
            self.milestonelink = ''
        self.implementationindex = self.implementations.index(
                                       self.implementation)
        self.priorityindex = self.priorities.index(self.priority)
        self.reviews = []
        self.assignee = lbp.assignee
        if (self.assignee is None):
            self.drafter = lbp.drafter
            if self.drafter is None:
                self.assigneename = ''
                self.assigneedisplay = ''
            else:
                self.assigneename = self.drafter.name
                try:
                    self.assigneedisplay = str(self.drafter.display_name)
                except UnicodeEncodeError:
                    self.assigneedisplay = self.drafter.name
                self.assigneedisplay = '<i>%s</i>' % self.assigneedisplay
        else:
            self.assigneename = self.assignee.name
            try:
                self.assigneedisplay = str(self.assignee.display_name)
            except UnicodeEncodeError:
                self.assigneedisplay = self.assignee.name

    def grab_xtra_info(self, gerritreviews):
        if self.whiteboard:
            matches = re.findall(
                          r'Addressed by: https://review.openstack.org/(\d+)',
                          bp.whiteboard)
            self.reviews.extend(self.grab_links(matches,
                                          gerritreviews.merged, "MERGED"))
            self.reviews.extend(self.grab_links(matches,
                                                gerritreviews.under_review,
                                                "NEEDSREVIEW"))

        self.impl_warn = ''
        self.impl_error = ''
        self.assignee_warn = ''
        self.assignee_error = ''

        # Design is not approved
        #if (bp.definition_status != "Approved"):
        #    impl_warn += '- Design not approved '

        # Spec is "Needs review" but has no branch up for review
        if (self.implementation == 'Needs Code Review'
            and len(self.reviews) == 0):
            self.impl_warn += '- Topic missing on reviews ? '

        # Spec isn't started but has branch merge proposal
        if (len(self.reviews) > 0 and (self.implementationindex > 8)):
            self.impl_warn += '- Spec has branch, should be started '

        # Spec has "Unknown" delivery status
        if (self.implementation == 'Unknown'):
            self.impl_error += '- Status needs to be set '

        # Assignee should not be a group
        if (self.assignee is None):
            if self.drafter is None:
                self.assignee_error += '- No assignee or drafter '
            else:
                self.assignee_warn += '- No assignee yet '
        else:
            if (self.assignee.is_team):
                self.assignee_warn += '- Should be assigned to an individual '

    def grab_links(self, matches, changes, image):
        links = {}
        if self.pname in changes:
            for change in changes[self.pname]:
                if (change['number'] in matches or
                    ('topic' in changes and
                     change['topic'].split("/")[-1] == bp.name)):
                    links[int(change['number'])] = change
        reviews = []
        for num in sorted(links.keys()):
            reviews.append(BlueprintReview(links[num], image))
        return reviews


class ExtendedBlueprintSet():
    def __init__(self, includelinks=False, reviews=None):
        self.bps = []
        self.includelinks = includelinks
        self.reviews = reviews

    def add(self, bp):
        newebp = ExtendedBlueprint(bp)
        if self.includelinks:
            newebp.grab_xtra_info(self.reviews)
        self.bps.append(newebp)


class CycleGaugeData(object):
    def __init__(self, config):
        self.ticks = ''
        self.end = -7
        for milestone in config['milestones']:
            self.ticks += ("''," * milestone[0])
            self.ticks += ("'%s'," % milestone[1])
            self.end += ((milestone[0] + 1) * 7)
        self.red = self.end - (config['milestones'][-1][0] + 1) * 7
        self.yellow = self.red - (config['milestones'][-2][0] + 1) * 7
        self.green = self.yellow - (config['milestones'][-3][0] + 1) * 7
        delta = config['releasedate'] - date.today()
        self.progress = self.end - delta.days


if __name__ == '__main__':

    template_dir = os.path.dirname(sys.argv[0])
    if len(sys.argv) < 2:
        print >> sys.stderr, "Usage: %s config.yaml" % sys.argv[0]
        sys.exit(1)

    with open(sys.argv[1]) as f:
        config = yaml.load(f)

    gaugedata = CycleGaugeData(config)

    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template('template.html')

    # Get changes from Gerrit
    reviews = GerritReviews(config['products'])

    # Log into LP
    lp = Launchpad.login_anonymously('releasestatus', 'production',
        '~/.launchpadlib-cache', version='devel')

    # Get the blueprints
    activebps = ExtendedBlueprintSet(includelinks=True, reviews=reviews)
    pastbps = ExtendedBlueprintSet(reviews=reviews)
    for p in config['products']:
        for bp in lp.projects[p].getSeries(
                  name=config['series']).valid_specifications:
            if bp.implementation_status == 'Implemented':
                pastbps.add(bp)
            else:
                activebps.add(bp)

    print template.render(series=config['series'],
                          gaugedata=gaugedata,
                          date=str(datetime.utcnow()),
                          activebps=activebps.bps,
                          pastbps=pastbps.bps)
