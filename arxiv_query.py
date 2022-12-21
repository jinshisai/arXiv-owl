# -*- coding: utf-8 -*-
'''
This module use the advanced search provided by the arXiv official:
 https://arxiv.org/search/advanced
'''


# modules
import os
import time
import datetime
import requests
from bs4 import BeautifulSoup
import re
import yaml
from yaml import Loader, Dumper
from dataclasses import dataclass
import textwrap
import slackweb



@dataclass
class Result:
    url: str
    title: str
    authors: str
    abstract: str
    words: list
    score: float = 0.0


class Article():
    """docstring for ClassName"""
    def __init__(self, title: str = 'none', authors: list = [],
        abstract:  str = 'none', links: dict = {}):
        self.title    = title
        self.authors  = authors
        self.abstract = abstract
        self.links    = links

    def writeout_authors(self):
        return ', '.join(self.authors)

    def writeout_links(self):
        outtext = ''
        for key in self.links.keys():
            outtext += '\n' + key + ': ' + self.links[key]
        return outtext


class ArXivQuery():
    """docstring for ClassName"""
    def __init__(self, arg):
        super(ArXivQuery, self).__init__()
        self.arg = 'arg'


def get_config() -> dict:
    file_abs_path = os.path.abspath(__file__)
    file_dir = os.path.dirname(file_abs_path)
    config_path = f'{file_dir}/config.yaml'

    if os.path.exists(config_path):
        with open(config_path, 'r') as yml:
            config = yaml.load(yml, Loader=Loader)
        return config
    else:
        #print('ERROR\tget_config: Cannot find config.yaml.')
        return 0

def arxiv_query(subject='Physics', days=2, 
    include_cross_listed=True, date_type='submitted_date',
    abstract=True, pages=200, score_threshold=0.0,
    keywords={}, subcat='astro-ph', slack_id = None,):
    '''

    Parameters
    ----------
    date_type: submitted_date or announcement_date.
    '''

    # set parameters
    form_url = 'https://arxiv.org/search/advanced'
    subject_list = {
    'Computer Science (cs)':'computer_science',
    'Physics': 'physics'
    }

    # terms
    nterms = 0
    terms_operator = 'AND'
    terms_field    = 'title'
    terms = '&'.join(
        ['terms-%i-operator=%s'%(nterms, terms_operator),
        'terms-%i-term='%nterms,
        'terms-%i-field=%s'%(nterms, terms_field)])

    # classification
    if type(subject) == str:
        subject = [subject]

    classification = '&'.join(['classification-%s=y'%subject_list[key] for key in subject])
    if 'Physics' in subject:
        classification += '&classification-physics_archives=%s'%subcat

    classification += '&classification-include_cross_list='
    if include_cross_listed:
        classification += 'include'
    else:
        classification += 'exclude'

    # subject/keywords if the automated input exist
    config = get_config()
    if config != 0:
        subcat = config['subject']
        keywords = config['keywords']
        score_threshold=float(config['score_threshold'])

    # date
    date = 'date-year=&date-filter_by=date_range' # currently support date-range only
    date_query_from = (datetime.datetime.today() - datetime.timedelta(days=days)).strftime('%Y-%m-%d')
    date_query_to   = (datetime.datetime.today() - datetime.timedelta(days=days-1)).strftime('%Y-%m-%d')
    date += '&date-from_date=%s&date-to_date=%s'%(date_query_from, date_query_to)
    date += '&date-date_type='+date_type

    # abstract
    abstract = 'abstracts=show' if abstract==True else 'abstracts=hide'

    # size
    size = 'size=%i'%pages

    # order
    order = 'order=-submitted_date' # sorted by submitted date (newest first)
    # example:
    # https://arxiv.org/search/advanced?advanced=
    #  &terms-0-operator=AND&terms-0-term=&terms-0-field=title
    #  &classification-physics=y&classification-physics_archives=astro-ph&classification-include_cross_list=include
    #  &date-year=&date-filter_by=date_range&date-from_date=2022-04-28&date-to_date=2022-04-29&date-date_type=submitted_date
    #  &abstracts=show&size=50&order=-announced_date_first
    search_url = \
    form_url + '?' + '&'.join(
        [
        'advanced=',
        terms,
        classification,
        date,
        abstract,
        size,
        order
        ])

    # html query
    search_results  = html_query(search_url)
    filtered_results = filter_by_score(search_results, keywords, score_threshold)

    if slack_id is None:
        slack_id = os.getenv("SLACK_ID")
    out_results(filtered_results, slack_id=slack_id)


def html_query(url) -> list:
    '''
    Extract information from html.
    '''
    # Get html
    res = requests.get(url)
    soup = BeautifulSoup(res.text, "html.parser")

    # get info. from arxiv results
    elems = soup.find_all('li', 'arxiv-result')
    results = []
    for elem in elems:
        # title
        e_title = elem.find('p', 'title')
        title   = e_title.contents[0].strip()
        # authors
        e_authors = elem.find('p', 'authors').find_all('a')
        authors   = [e_i.contents[0] for e_i in e_authors]
        # abstract
        e_abstract = elem.find('p', 'abstract')
        abstract   = e_abstract.find('span', 'abstract-full').contents[0].strip()
        # links
        e_links = elem.find_all('a', href=re.compile('arxiv'))
        links = {}
        for e_i in e_links:
            key = 'arxiv' if 'arxiv' in e_i.text.lower() else e_i.text
            links[key] = e_i.get(key='href')

        article = Article(title, authors, abstract, links)
        results.append(article)

    return results


def score_article(text: str, keywords: dict) -> (float, list):
    sum_score = 0.0
    hit_kwd_list = []

    for word in keywords.keys():
        score = keywords[word]
        if word.lower() in text.lower():
            sum_score += score
            hit_kwd_list.append(word)
    return sum_score, hit_kwd_list



def filter_by_score(search_results, keywords: dict, score_threshold: float) -> list:
    results = []

    for article in search_results:
        title    = article.title
        authors  = article.writeout_authors()
        abstract = article.abstract
        url      = article.links['arxiv']
        score, hit_keywords = score_article(abstract, keywords)
        if (score != 0) and (score >= score_threshold):
            # edited by J.Sai, 3/6/21
            # turned off translation

            '''
            # original
            title_trans = get_translated_text('ja', 'en', title)
            abstract = abstract.replace('\n', '')
            abstract_trans = get_translated_text('ja', 'en', abstract)
            # abstract_trans = textwrap.wrap(abstract_trans, 40)  # 40行で改行
            # abstract_trans = '\n'.join(abstract_trans)
            result = Result(
                    url=url, title=title_trans, abstract=abstract_trans,
                    score=score, words=hit_keywords)
            '''

            # added
            #abstract_en = textwrap.wrap(abstract, 90)  # 90行で改行
            #abstract_en = '\n'.join(abstract_en)
            abstract_en = abstract
            result = Result(
                    url=url, title=title, authors=authors,
                    abstract=abstract_en, score=score, words=hit_keywords)

            results.append(result)
    return results


def out_results(results: list, slack_id: str = None,
    line_token: str = None):
    star  = '*'*80
    today = datetime.date.today()
    n_articles = len(results)
    text = f'{star}\n \t \t {today}\tnum of articles = {n_articles}\n{star}'
    send2app(text, slack_id=slack_id, line_token=line_token)

    for result in sorted(results, reverse=True, key=lambda x: x.score):

        url      = result.url
        title    = result.title
        authors  = result.authors
        abstract = result.abstract
        word     = result.words
        score    = result.score

        text = f'\n score: `{score}`'\
               f'\n hit keywords: `{word}`'\
               f'\n url: {url}'\
               f'\n title:    {title}'\
               f'\n authours:    {authors}'
        text = text + f'\n abstract:'\
               f'\n \t {abstract}'\
               f'\n {star}'

        #print(text)
        send2app(text, slack_id=slack_id, line_token=line_token)


def send2app(text: str, slack_id: str, line_token: str) -> None:
    # slack
    if slack_id is not None:
        slack = slackweb.Slack(url=slack_id)
        slack.notify(text=text)

    # line
    if line_token is not None:
        line_notify_api = 'https://notify-api.line.me/api/notify'
        headers = {'Authorization': f'Bearer {line_token}'}
        data = {'message': f'message: {text}'}
        requests.post(line_notify_api, headers=headers, data=data)

# main
def main():
    arxiv_query(days=2)


if __name__ == '__main__':
    main()