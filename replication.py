import os
import shutil
import time
import threading
import logging
from flask import Flask

script_dir = os.path.dirname(os.path.abspath(__file__))
source_tinydb_db_path = os.path.join(script_dir, 'customers.json')
replicas_dir = os.path.join(script_dir, 'replicas')

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def replicate_tinydb():
    try:
        os.makedirs(replicas_dir, exist_ok=True)

        if os.path.exists(source_tinydb_db_path):
            for replica_id in range(1, 5):
                destination_tinydb_db_path = os.path.join(replicas_dir, f'customers_replica{replica_id}.json')
                shutil.copy(source_tinydb_db_path, destination_tinydb_db_path)
                logger.info(f"TinyDB database replicated successfully for replica {replica_id}")
                print(f"TinyDB database replicated successfully for replica {replica_id} at",
                      time.strftime('%Y-%m-%d %H:%M:%S'))
        else:
            print('Source TinyDB database file not found.')
            logger.error('Source TinyDB database file not found.')
    except Exception as e:
        logger.error("Error occurred during replication:", str(e))
        print("Error occurred during replication:", str(e))


def create_replica_app(replica_path, port):
    app = Flask(__name__)

    @app.route('/customers', methods=['GET'])
    def get_data():
        print('Received request to retrieve data from the replica')
        logger.info('Received request to retrieve data from the replica')
        with open(replica_path, 'r') as f:
            data = f.read()
        return data

    app.run(debug=True, host='0.0.0.0', port=port, use_reloader=False)

def main():
    while True:
        replicate_tinydb()
        time.sleep(1)

        threads = []
        for replica_id in range(1, 5):
            replica_path = os.path.join(replicas_dir, f'customers_replica{replica_id}.json')
            thread = threading.Thread(target=create_replica_app, args=(replica_path, 5070 + replica_id))
            thread.start()
            threads.append(thread)

        for thread in threads:
            thread.join()


if __name__ == "__main__":
    main()