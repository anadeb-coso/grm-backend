"""Compare les comptages de lignes entre la base MySQL source (`grm`, config locale) et la base
Postgres cible (`grm_db`), pour les tables de l'app existante transférée via dumpdata/loaddata
(voir CLAUDE.md §5.4). Nécessite MySQLdb (mysqlclient) et psycopg2, déjà dans requirements.txt.

Usage : python scripts/verify_migration.py
"""
import MySQLdb
import psycopg2

MYSQL_CONFIG = dict(host='localhost', user='root', passwd='', db='grm')
POSTGRES_CONFIG = dict(host='localhost', port=5432, dbname='grm_db', user='postgres', password='root')

TABLES = [
    'auth_group',
    'authentication_user',
    'authentication_governmentworker',
    'authentication_cdata',
    'authentication_pdata',
    'privacy_issuecategorypassword',
    'issue_wave',
]


def main():
    mysql_conn = MySQLdb.connect(**MYSQL_CONFIG)
    pg_conn = psycopg2.connect(**POSTGRES_CONFIG)

    all_ok = True
    for table in TABLES:
        with mysql_conn.cursor() as c:
            c.execute(f'SELECT COUNT(*) FROM {table}')
            mysql_count = c.fetchone()[0]
        with pg_conn.cursor() as c:
            c.execute(f'SELECT COUNT(*) FROM {table}')
            pg_count = c.fetchone()[0]

        ok = mysql_count == pg_count
        all_ok = all_ok and ok
        status = 'OK' if ok else 'ECART !'
        print(f'{table}: MySQL={mysql_count} Postgres={pg_count} [{status}]')

    mysql_conn.close()
    pg_conn.close()

    if not all_ok:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
