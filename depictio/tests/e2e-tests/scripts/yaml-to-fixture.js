const yaml = require('js-yaml')
const fs = require('fs')
const path = require('path')

// Read YAML file
const yamlPath = path.resolve(__dirname, '../../../api/v1/configs/initial_users.yaml')
const config = yaml.load(fs.readFileSync(yamlPath, 'utf8'))

// Extract test user
const testUser = config.users[1]

// Write to fixture
const fixturePath = path.resolve(__dirname, '../cypress/fixtures/test-credentials.json')
fs.writeFileSync(fixturePath, JSON.stringify({ testUser }, null, 2))

console.log('Credentials extracted to fixtures!')
