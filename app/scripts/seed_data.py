#!/usr/bin/env python3
"""Seed script for LibrarySystemPRO.
Usage: python scripts/seed_data.py --students 5000 --books 100000
"""
import os
import random
import argparse
from faker import Faker
from tqdm import tqdm
from datetime import datetime

from app import create_app, db, Student, Book

fake = Faker()

def bulk_insert_students(n, batch=1000):
    students = []
    for i in range(n):
        sid = f"S{100000 + i}"
        students.append(Student(student_id=sid, full_name=fake.name(), class_name=str(random.randint(1,12)), section=random.choice(['A','B','C']), email=fake.email(), phone=fake.phone_number(), enrollment_year=random.randint(2015, 2026)))
        if len(students) >= batch:
            db.session.bulk_save_objects(students)
            db.session.commit()
            students = []
    if students:
        db.session.bulk_save_objects(students)
        db.session.commit()


def bulk_insert_books(n, batch=1000):
    books = []
    for i in range(n):
        accession = f"ACC{200000 + i}"
        title = fake.sentence(nb_words=4).rstrip('.')
        books.append(Book(accession_number=accession, isbn=str(9780000000000 + i), title=title, author=fake.name(), publisher=fake.company(), category=random.choice(['Science','Math','History','Fiction','Technology','Arts']), publication_year=random.randint(1970,2024), purchase_price=round(random.uniform(100, 2000),2), quantity=random.randint(1,5), available_copies=random.randint(0,5), shelf_location=f"S-{random.randint(1,50)}"))
        if len(books) >= batch:
            db.session.bulk_save_objects(books)
            db.session.commit()
            books = []
    if books:
        db.session.bulk_save_objects(books)
        db.session.commit()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--students', type=int, default=5000)
    parser.add_argument('--books', type=int, default=100000)
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        print('Seeding students...')
        bulk_insert_students(args.students)
        print('Seeding books...')
        bulk_insert_books(args.books)
        print('Done')
