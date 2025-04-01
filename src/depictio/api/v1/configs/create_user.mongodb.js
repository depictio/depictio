// MongoDB Playground
// Use Ctrl+Space inside a snippet or a string literal to trigger completions.

// The current database to use.
use('depictioDB');

// Create a new document in the collection.
db.getCollection('users').insertOne({
    "username": "Cezanne",
    "password": "Paul",
});
