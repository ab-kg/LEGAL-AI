import os
from pymongo import MongoClient

mongo_uri = "mongodb+srv://nishanthattarki23_db_user:UUvoEpHvInqXG5tq@cluster0.zs1s9fu.mongodb.net/?appName=Cluster0"
client = MongoClient(mongo_uri)
db = client.get_database("legal_ai") # wait, what is the DB name? Let's check what app.py uses.

print("Databases:", client.list_database_names())
