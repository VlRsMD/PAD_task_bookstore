from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from tinydb import TinyDB, Query
import os
import shutil
import json
from rediscluster import RedisCluster
import logging


app = Flask(__name__)

databases_created = False

script_dir = os.path.dirname(os.path.abspath(__file__))

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(script_dir, 'bookstore.db')
db = SQLAlchemy(app)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

source_tinydb_db_path = os.path.join(script_dir, 'customers.json')
replicas_dir = os.path.join(script_dir, 'replicas')

# Configure Redis nodes and Redis Cluster
startup_nodes = [
    {"host": "redis-node1", "port": "7000"},
    {"host": "redis-node2", "port": "7001"},
    {"host": "redis-node3", "port": "7002"},
    {"host": "redis-node4", "port": "7003"},
    {"host": "redis-node5", "port": "7004"},
    {"host": "redis-node6", "port": "7005"},
]
redis_cluster = RedisCluster(startup_nodes=startup_nodes, decode_responses=True)

class Book(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    author = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)

db_customers = TinyDB(os.path.join(script_dir, 'customers.json'))
customers_table = db_customers.table('customers')

def create_databases():
    global databases_created
    if not databases_created:
        with app.app_context():
            db.create_all()
            if not Book.query.first():
                initial_books = [
                    {'title': 'The Great Gatsby', 'author': 'F. Scott Fitzgerald', 'price': 10.99, 'quantity': 5},
                    {'title': 'To Kill a Mockingbird', 'author': 'Harper Lee', 'price': 12.50, 'quantity': 3}
                ]
                for book_data in initial_books:
                    new_book = Book(**book_data)
                    db.session.add(new_book)
                db.session.commit()

        if not customers_table.all():
            customers_table.insert_multiple([
                {'name': 'John Doe', 'email': 'john@example.com', 'orders_count': 0},
                {'name': 'Alice Smith', 'email': 'alice@example.com', 'orders_count': 0}
            ])

        databases_created = True

@app.route('/books', methods=['GET'])
def get_books():
    print('Received request to fetch books.')
    logger.info('Received request to fetch books.')
    cached_books = redis_cluster.get('books')
    if cached_books:
        print('Retrieving books from the Redis cache.')
        logger.info('Retrieving books from the Redis cache.')
        return jsonify(json.loads(cached_books))

    books = Book.query.all()
    output = [{'id': book.id, 'title': book.title, 'author': book.author, 'price': book.price, 'quantity': book.quantity} for book in books]

    # Add books to Redis cache if they are not yet cached
    redis_cluster.set('books', json.dumps(output))
    print('Successfully added books to the Redis cache.')
    logger.info('Successfully added books to the Redis cache.')

    return jsonify(output)

@app.route('/books', methods=['POST'])
def add_book():
    print('Received request to add a new book.')
    logger.info('Received request to add a new book.')
    data = request.get_json()
    new_book = Book(title=data['title'], author=data['author'], price=data['price'], quantity=data['quantity'])
    db.session.add(new_book)
    db.session.commit()

    if redis_cluster.exists('books'):
        redis_cluster.delete('books')
        print('Redis cache cleared.')
        logger.info('Redis cache cleared.')

    # Replicate the updated database data after a new book is added
    for replica_id in range(1, 5):
        replica_db_path = os.path.join(replicas_dir, f'customers_replica{replica_id}.json')
        try:
            shutil.copy(source_tinydb_db_path, replica_db_path)
            print(f"Data replicated successfully in replica {replica_id}")
            logger.info(f"Data replicated successfully in replica {replica_id}")
        except Exception as e:
            print(f"Failed to replicate data in replica {replica_id}: {str(e)}")
            logger.error(f"Failed to replicate data in replica {replica_id}: {str(e)}")

    print('New book added successfully.')
    logger.info('New book added successfully.')
    return jsonify({'message': 'New book added successfully!'})

# Function implementing the 2 Phase Commit
@app.route('/books-2pc', methods=['POST'])
def add_book_2pc():
    print('Received request to add a new book performing 2 Phase Commit.')
    logger.info('Received request to add a new book.')

    # Add new book if both databases are connected, if not - output error
    if books_db_connected() and customers_db_connected():
        try:
            data = request.get_json()
            new_book = Book(title=data['title'], author=data['author'], price=data['price'], quantity=data['quantity'])
            db.session.add(new_book)
            db.session.commit()

            if redis_cluster.exists('books'):
                redis_cluster.delete('books')
                print('Redis cache cleared.')
                logger.info('Redis cache cleared.')

            # Increment the 'orders_count' value by 1 for every customer
            increment_order_count_for_customers()

            # Replicate the updated database data after a new book is added
            for replica_id in range(1, 5):
                replica_db_path = os.path.join(replicas_dir, f'customers_replica{replica_id}.json')
                try:
                    shutil.copy(source_tinydb_db_path, replica_db_path)
                    print(f"Data replicated successfully in replica {replica_id}")
                    logger.info(f"Data replicated successfully in replica {replica_id}")
                except Exception as e:
                    print(f"Failed to replicate data in replica {replica_id}: {str(e)}")
                    logger.error(f"Failed to replicate data in replica {replica_id}: {str(e)}")

            print('New book added successfully.')
            logger.info('New book added successfully.')
            return jsonify({'message': 'New book added successfully!'})
        except Exception as e:
            print(f'Failed to add customer: {str(e)}')
            logger.error(f'Failed to add customer: {str(e)}')
            return jsonify({'error': f'Failed to add customer: {str(e)}'}), 500
    else:
        print('Failed to add customer: One or both databases are not connected')
        logger.error('Failed to add customer: One or both databases are not connected')
        return jsonify({'error': 'Failed to add customer: One or both databases are not connected'}), 500

# Function to check if the books database is connected
def books_db_connected():
    try:
        db.session.query(Book).first()
        print('Connected to the books database successfully!')
        logger.info('Connected to the books database successfully!')
        return jsonify({'message': 'Connected to the books database successfully!'})
    except Exception as e:
        print(f'Failed to connect to books database: {str(e)}')
        logger.error(f'Failed to connect to books database: {str(e)}')
        return jsonify({'error': f'Failed to connect to books database: {str(e)}'}), 500


# Function to check if the customers database is connected
def customers_db_connected():
    try:
        customers_table.search(Query().name.exists())
        print('Connected to the customers database successfully!')
        logger.info('Connected to the customers database successfully!')
        return jsonify({'message': 'Connected to the customers database successfully!'})
    except Exception as e:
        print(f'Failed to connect to customers database: {str(e)}')
        logger.error(f'Failed to connect to customers database: {str(e)}')
        return jsonify({'error': f'Failed to connect to customers database: {str(e)}'}), 500

# Function to increment the 'orders_count' value for every customer
def increment_order_count_for_customers():
    with open('customers.json', 'r') as f:
        customers_data = json.load(f)

    for customer_id, customer_info in customers_data['customers'].items():
        updated_orders_count = customer_info.get('orders_count', 0) + 1
        customer_info['orders_count'] = updated_orders_count

    with open('customers.json', 'w') as f:
        json.dump(customers_data, f)

    print('Orders count incremented for all customers.')
    logger.info('Orders count incremented for all customers.')
    return jsonify({'message': 'Orders count incremented for all customers.'})

@app.route('/books/<int:book_id>', methods=['PUT'])
def update_book(book_id):
    print('Received request to update book.')
    logger.info('Received request to update book.')
    book = Book.query.get_or_404(book_id)
    data = request.get_json()
    book.title = data['title']
    book.author = data['author']
    book.price = data['price']
    book.quantity = data['quantity']
    db.session.commit()

    if redis_cluster.exists('books'):
        redis_cluster.delete('books')
        print('Redis cache cleared.')
        logger.info('Redis cache cleared.')

    print('Book updated successfully!')
    logger.info('Book updated successfully!')
    return jsonify({'message': 'Book updated successfully!'})

@app.route('/customers', methods=['GET'])
def get_customers():
    print('Received request to fetch customers.')
    logger.info('Received request to fetch customers.')
    return jsonify(customers_table.all())

@app.route('/customers', methods=['POST'])
def add_customer():
    print('Received request to add a new customer.')
    logger.info('Received request to add a new customer.')
    data = request.get_json()
    new_customer = {
        'name': data['name'],
        'email': data['email'],
        'orders_count': 0
    }
    customers_table.insert(new_customer)

    # Replicate the updated database data after a new customer is added
    for replica_id in range(1, 5):
        replica_db_path = os.path.join(replicas_dir, f'customers_replica{replica_id}.json')
        try:
            shutil.copy(source_tinydb_db_path, replica_db_path)
            print(f"Data replicated successfully in replica {replica_id}")
            logger.info(f"Data replicated successfully in replica {replica_id}")
        except Exception as e:
            print(f"Failed to replicate data in replica {replica_id}: {str(e)}")
            logger.error(f"Failed to replicate data in replica {replica_id}: {str(e)}")

    print('New customer added successfully!')
    logger.info('New customer added successfully!')
    return jsonify({'message': 'New customer added successfully!'})


@app.route('/customers/<int:customer_id>', methods=['PUT'])
def update_customer(customer_id):
    print('Received request to update customer.')
    logger.info('Received request to update customer.')
    try:
        data = request.get_json()
        updated_customer = {
            'name': data['name'],
            'email': data['email']
        }

        with open(source_tinydb_db_path, 'r') as f:
            customers_data = json.load(f)

        if str(customer_id) in customers_data['customers']:
            customers_data['customers'][str(customer_id)].update(updated_customer)

            with open(source_tinydb_db_path, 'w') as f:
                json.dump(customers_data, f, indent=None)

            # Replicate the updated database data after a new customer is added
            for replica_id in range(1, 5):
                replica_db_path = os.path.join(replicas_dir, f'customers_replica{replica_id}.json')
                try:
                    shutil.copy(source_tinydb_db_path, replica_db_path)
                    print(f"Data replicated successfully in replica {replica_id}")
                    logger.info(f"Data replicated successfully in replica {replica_id}")
                except Exception as e:
                    print(f"Failed to replicate data in replica {replica_id}: {str(e)}")
                    logger.error(f"Failed to replicate data in replica {replica_id}: {str(e)}")

            print('Customer updated successfully!')
            logger.info('Customer updated successfully!')
            return jsonify({'message': 'Customer updated successfully!'})
        else:
            print('Customer ID not found.')
            logger.error('Customer ID not found.')
            return jsonify({'error': 'Customer ID not found.'}), 404
    except Exception as e:
        print(str(e))
        logger.error(str(e))
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    create_databases()
    app.run(debug=True, host='0.0.0.0', port=5050)
