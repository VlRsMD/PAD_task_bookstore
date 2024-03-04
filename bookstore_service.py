from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from tinydb import TinyDB, Query
import os
import shutil
import json
import logging
import hashlib
from rediscluster import RedisCluster

app = Flask(__name__)

databases_created = False

script_dir = os.path.dirname(os.path.abspath(__file__))

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(script_dir, 'bookstore.db')
db = SQLAlchemy(app)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

source_tinydb_db_path = os.path.join(script_dir, 'customers.json')
replicas_dir = os.path.join(script_dir, 'replicas')

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

# Cache node containing data
class CacheNode:
    def __init__(self, node_id):
        self.node_id = node_id
        self.data = {}

# Consistent hashing logic to distribute keys across nodes
class ConsistentHashing:
    def __init__(self, num_nodes):
        # Create a list of cache nodes
        self.nodes = [CacheNode(node_id) for node_id in range(num_nodes)]

    # Get the node responsible for a given key based on consistent hashing
    def get_node(self, key):
        # Calculate the hash of the key
        hash_value = hashlib.sha1(key.encode()).hexdigest()
        # Map the hash to a node index
        node_index = int(hash_value, 16) % len(self.nodes)
        # Return the corresponding node
        return self.nodes[node_index]

# Distributed cache with sharding and consistent hashing
class DistributedCache:
    def __init__(self, num_shards, num_replicas):
        self.num_shards = num_shards
        self.num_replicas = num_replicas
        # Create a list of sharding instances
        self.shards = [ConsistentHashing(num_replicas) for _ in range(num_shards)]

    # Get the value associated with a key from the cache
    def get(self, key):
        # Determine the shard index based on the hash of the key
        shard_index = hash(key) % self.num_shards
        # Get the node responsible for the key within the shard
        node = self.shards[shard_index].get_node(key)
        # Return the value associated with the key in the node's data
        return node.data.get(key)

    # Set a key-value pair in the cache
    def set(self, key, value):
        # Determine the shard index based on the hash of the key
        shard_index = hash(key) % self.num_shards
        # Get the node responsible for the key within the shard
        node = self.shards[shard_index].get_node(key)
        # Set the key-value pair in the node's data
        node.data[key] = value

    # Clear the cache for a specific key
    def clear(self, key):
        # Determine the shard index based on the hash of the key
        shard_index = hash(key) % self.num_shards
        # Get the node responsible for the key within the shard
        node = self.shards[shard_index].get_node(key)
        # Remove the key from the node's data if it exists
        if key in node.data:
            del node.data[key]

    # Check if a cache with a specific key exists
    def exists(self, key):
        # Determine the shard index based on the hash of the key
        shard_index = hash(key) % self.num_shards
        # Get the node responsible for the key within the shard
        node = self.shards[shard_index].get_node(key)
        # Return True if the key exists in the node's data, False otherwise
        return key in node.data

cache = DistributedCache(num_shards=4, num_replicas=3)

@app.route('/books', methods=['GET'])
def get_books():
    print('Received request to fetch books.')
    logger.info('Received request to fetch books.')

    books = Book.query.all()
    output = [{'id': book.id, 'title': book.title, 'author': book.author, 'price': book.price, 'quantity': book.quantity} for book in books]

    cached_books = cache.get('books')
    if cached_books:
        print('Retrieving books from the cache.')
        logger.info('Retrieving books from the cache.')
        return cached_books

    # Add books to cache if they are not yet cached
    cache.set('books', jsonify(output))
    print('Successfully added books to the cache.')
    logger.info('Successfully added books to the cache.')

    return jsonify(output)

@app.route('/books', methods=['POST'])
def add_book():
    print('Received request to add a new book.')
    logger.info('Received request to add a new book.')
    data = request.get_json()
    new_book = Book(title=data['title'], author=data['author'], price=data['price'], quantity=data['quantity'])
    db.session.add(new_book)
    db.session.commit()

    if cache.exists('books'):
        cache.clear('books')
        print('Books cache cleared.')
        logger.info('Books cache cleared.')

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

            if cache.exists('books'):
                cache.clear('books')
                print('Books cache cleared.')
                logger.info('Books cache cleared.')

            # Increment the 'orders_count' value by 1 for every customer
            increment_order_count_for_customers()

            if cache.exists('customers'):
                cache.clear('customers')
                print('Customers cache cleared.')
                logger.info('Customers cache cleared.')

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

    if cache.exists('books'):
        cache.clear('books')
        print('Books cache cleared.')
        logger.info('Books cache cleared.')

    print('Book updated successfully!')
    logger.info('Book updated successfully!')
    return jsonify({'message': 'Book updated successfully!'})

@app.route('/customers', methods=['GET'])
def get_customers():
    print('Received request to fetch customers.')
    logger.info('Received request to fetch customers.')

    cached_customers = cache.get('customers')
    if cached_customers:
        print('Retrieving customers from the cache.')
        logger.info('Retrieving customers from the cache.')
        return cached_customers

    # Add customers to cache if they are not yet cached
    cache.set('customers', jsonify(customers_table.all()))
    print('Successfully added customers to the cache.')
    logger.info('Successfully added customers to the cache.')

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

    if cache.exists('customers'):
        cache.clear('customers')
        print('Customers cache cleared.')
        logger.info('Customers cache cleared.')

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

            if cache.exists('customers'):
                cache.clear('customers')
                print('Customers cache cleared.')
                logger.info('Customers cache cleared.')

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