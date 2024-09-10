db.createUser(
    {
      user: "appUser",
      pwd: "password123",
      roles: [ { role: "readWrite", db: "yourDatabase" } ]
    }
  )
  