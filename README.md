This is a repository containing the source code of the Bookstore application implemented for the purpose of the Distributed Systems course at the Technical University of Moldova. In this application a service representing a REST API is created. 
That service has 7 endpoints supporting the GET, POST and PUT requests. The service is connected to two separate databases. First database is an SQLite SQL database and it stores data referring to the books entity. 
The second database is a TinyDB NoSQL database and it stores the data referring to the customers entity. For each entity (books and customers) and corresponding databases the service implements functions which allow to perform corresponding GET, POST and PUT request. 
The source code of the bookstore service can be found in the **'bookstore_service.py'** file.

One of the databases connected to the bookstore service, namely the TinyDB NoSQL database that stores the customers data, is replicated. Four replicas of this database are created. Each of the replicas is accessible on its corresponding port. 
The replicas support GET, POST and PUT methods. The functionality of the GET method for replicas can be checked by accessing the corresponding endpoints of the replicas which output the replicated data from the customers TinyDB database. 
And each time when POST or PUT requests are performed to the bookstore service customers initial endpoint, the data is also either added (in case of POST method) or updated (in case of PUT method) in all the replicas. 
The source code for initializing the replicas is contained in the **'replication.py'** file. Also, the 4 replicated databases can be found inside the **'replicas'** folder in the project.

One of the endpoints of the bookstore service, namely the **'/books-2pc'** endpoint, is designed for performing POST requests implementing 2 Phase Commit. 
First, the database connection is checked to the both databases (books database and customers database). If one of the databases or both databases are not connected, then an error is returned and commit is not done. 
If both databases are connected, then a new book is added to the books database, and simultaneously in the customer database the *orders_count* value is incremented by 1 for every customer. 

For consistent hashing Redis cluster with 6 Redis nodes is implemented. This Redis cluster has 3 master and 3 slave nodes. The configuration files for each Redis node can be found in the **cluster-test** folder and the corresponding subfolders for each node. 
The Redis nodes and the corresponding cluster are created using Docker.
On each GET request to fetch the books from the database the books retrieved from the database are added to the Redis cache. 
Then each time a POST or PUT request is made, the Redis cache is cleared. Sharding is implemented automatically by Redis. 

The project is dockerized and the configurations for the dockerization can be found in the **'docker-compose.yml'** file. 

The set of HTTP requests for this project can be found in the **'postman-collection'** folder.
