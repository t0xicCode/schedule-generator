#!/usr/bin/env python

from __future__ import print_function
import argparse
import sys
import time
import traceback
import urllib2
import ssl
import re
import multiprocessing
from multiprocessing import Lock, Queue, JoinableQueue

from bs4 import BeautifulSoup


def process_data(main_q, skipped_q, db_queue, db_lock):
    """
    Downloads and processes the course info
    """

    exitFlag = False
    while not exitFlag:
        if main_q.empty():
            exitFlag = True
            break
        else:
            course = main_q.get()

        course_list = []
        section_list = []
        activity_list = []

        try:
            retry = 5  # This loop will restart at most 5 times
            while retry:
                html = ''
                try:
                    context = ssl.SSLContext(ssl.PROTOCOL_TLSv1)
                    site = urllib2.urlopen(
                        'https://web30.uottawa.ca/v3/SITS/timetable/Course.aspx?code={0}'.format(course), context=context)
                    html = site.read()
                except urllib2.HTTPError as e:
                    print('Server error: {0}.'.format(e.reason))
                    if retry:
                        print('Waiting 2 seconds...')
                        time.sleep(2)
                        retry -= 1
                        continue
                    else:
                        print('Skipping course')
                        skipped_q.put('{0}, ran out of retries, HTTPError'.format(course))
                        break
                except urllib2.URLError as e:
                    print('Internet problem: {0}.'.format(e.reason))
                    if retry:
                        print('Waiting 5 seconds...')
                        time.sleep(5)
                        retry -= 1
                        continue
                    else:
                        print('Skipping course')
                        skipped_q.put('{0}, ran out of retries, URLError'.format(course))
                        break
                finally:
                    try:
                        site.close()
                    except NameError:
                        pass

                soup = BeautifulSoup(html)
                content = soup.find('div', id='main-content')

                # Get course title
                title = re.search(r'{0} - (.*)'.format(course), content.find('h1').get_text())
                if title is None:
                    skipped_q.put('{0}, no title'.format(course))
                    break
                else:
                    title = title.group(1).strip()

                if ',' in title:
                    title = u'"{0}"'.format(title)

                # Get all semesters
                sections = False
                for semester in content.find('div', id='schedule').find_all('div', class_='schedule'):
                    # Get semester integer
                    semester_id = semester.get('id')

                    for section in semester.find_all('table'):
                        _section_title = section.find('td', class_='Section').contents[0]
                        section_id = re.search(r'{0} (.*)'.format(course), _section_title)
                        if section_id is not None:
                            section_id = section_id.group(1).strip()

                        one_dgd = 0
                        one_lab = 0
                        one_tut = 0

                        _footer = section.find('tr', class_='footer')
                        if _footer is not None:
                            _footer_content = _footer.find('td').get_text()

                            if u'Only one discussion group' in _footer_content:
                                one_dgd = 1

                            if u'Only one laboratory' in _footer_content:
                                one_lab = 1

                            if u'Only one tutorial' in _footer_content:
                                one_tut = 1

                        activities = False
                        for activity in section.find_all('td', class_='Activity'):
                            # Lecture, Lab, etc.
                            activity_type = re.search(r'([a-zA-Z ]+)', activity.get_text()).group(1).strip()

                            # 1, 2, etc.
                            activity_num = re.search(r'(\d+)', activity.get_text()).group(1).strip()

                            # Day
                            _day = activity.next_sibling

                            # Sunday - Saturday
                            activity_day = re.search(r'([a-zA-Z ]+)', _day.get_text())
                            if activity_day is None:
                                activity_day = u'N/A'
                            else:
                                activity_day = activity_day.group(1).strip()

                            # 08:30 - 22:00
                            activity_time_start = re.search(r'(\d{2}:\d{2}) -', _day.get_text()).group(1).strip()
                            activity_time_end = re.search(r'- (\d{2}:\d{2})', _day.get_text()).group(1).strip()

                            # Place
                            _place = _day.next_sibling

                            # eg: SMD 224
                            activity_place = _place.get_text().strip()
                            if u'available' in activity_place:
                                activity_place = u'N/A'

                            # Professor
                            _professor = _place.next_sibling

                            # eg: John Smith
                            activity_prof = _professor.get_text().strip()

                            if activity_prof == u'&nbsp;' or u'available' in activity_prof:
                                activity_prof = u'N/A'

                            # Add activity to list
                            if section_id is None:
                                string = u'{0},{1},{2},{4},{5},{6},{7},{8},{9}'
                            else:
                                string = u'{0},{1},{2}{3},{4},{5},{6},{7},{8},{9}'

                            activity_list.append(
                                string.format(
                                    activity_type, activity_num, course, section_id, semester_id, activity_day,
                                    activity_time_start, activity_time_end, activity_place, activity_prof
                                )
                            )
                            activities = True

                        if activities:
                            # If there was at least one activity, add the section to the sections list.
                            if section_id is None:
                                string = u'{0},{0},{2},{3},{4},{5}'
                            else:
                                string = u'{0}{1},{0},{2},{3},{4},{5}'

                            section_list.append(
                                string.format(
                                    course, section_id, semester_id, str(one_dgd), str(one_tut), str(one_lab)
                                )
                            )
                            sections = True

                if sections:
                    # If there was at least one section, add the course to the courses list.
                    full_course = u'{0},{1}'.format(course, title)
                    # Add course, sections, and activities to queue
                    db_lock.acquire()
                    db_queue.put(
                        [full_course, section_list, activity_list]
                    )
                    db_lock.release()
                else:
                    # Otherwise add it to the skipped list so that the user can double-check it
                    skipped_q.put('{0}, no sections'.format(course))

                break  # break out of the retry loop

            if exitFlag == True:
                break
            else:
                print('[{0}][Course: {1}]'.format(multiprocessing.current_process().name, course))
                main_q.task_done()
        except AttributeError as e:
            print('Error in process {0} with course {1}: {2}'.format(multiprocessing.current_process().name, course,
                                                                     e.message), file=sys.stderr)
            traceback.print_exc()

def activity_key(activity):
    # Key is after 2nd comma
    print (activity)
    return activity.split(',')[2]

def main(course_file='courses.txt', clear_db=True):
    """Main method/entrypoint
    """

    # Courses
    work_queue = JoinableQueue()
    skipped_queue = Queue(0)

    with open(course_file, "r") as f:
        for line in f:
            work_queue.put(line.strip())

    # For holding the database info
    db_queue = Queue()
    db_lock = Lock()

    # Create the threads
    process_list = []
    for i in range(multiprocessing.cpu_count()):
        p = multiprocessing.Process(target=process_data,
                                    args=(work_queue, skipped_queue, db_queue, db_lock))
        process_list.append(p)
        p.start()


    work_queue.join()
    work_queue.close()

    db_lock.acquire()
    print('Done work. Got {0} courses, skipped {1}'.format(db_queue.qsize(), skipped_queue.qsize()))
    db_lock.release()

    print()
    # Announce skipped courses
    with open('skippedCourses.txt', 'w') as f:
        if not skipped_queue.empty():
            print('These courses were skipped: ')
            while not skipped_queue.empty():
                skipped_course = skipped_queue.get()
                print('  {0}'.format(skipped_course))
                to_file = skipped_course.split(',', 1)[0]
                f.write(u'{0}\n'.format(to_file).encode('utf8'))
        print()

    db_courses = Queue(0)
    db_sections = Queue(0)
    db_activities = Queue(0)

    while not db_queue.empty():
        course = db_queue.get()
        # course name
        db_courses.put(course[0])
        # sections
        for section in course[1]:
            db_sections.put(section)
        # activities
        for activity in course[2]:
            db_activities.put(activity)



    # Print total count of all items
    print('Courses: {0}'.format(db_courses.qsize()))
    print('Sections: {0}'.format(db_sections.qsize()))
    print('Activities: {0}'.format(db_activities.qsize()))

    # Write courses to files
    with open('db_courses.csv', 'w' if clear_db else 'a') as f:
        while not db_courses.empty():
            f.write(u'{0}\n'.format(db_courses.get()).encode('utf8'))

    # Write sections to files
    with open('db_sections.csv', 'w' if clear_db else 'a') as f:
        while not db_sections.empty():
            f.write(u'{0}\n'.format(db_sections.get()).encode('utf8'))

    # Write activities to files
    with open('db_activities.csv', 'w' if clear_db else 'a') as f:
        while not db_activities.empty():
            f.write(u'{0}\n'.format(db_activities.get()).encode('utf8'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Generate a course list.')
    parser.add_argument('-s', '--skipped', help='run over the skipped courses instead of the full list',
                        action='store_const', const='skippedCourses.txt', default='courses.txt')
    parser.add_argument('-n', '--no-clear-db', help='clear the DB prior to saving the results', action='store_true',
                        default=False)
    parser.add_argument('--version', action='version', version='%(prog)s 2.0')
    args = parser.parse_args()
    args.no_clear_db = True if args.skipped == 'skippedCourses.txt' else args.no_clear_db
    main(course_file=args.skipped, clear_db=(not args.no_clear_db))
