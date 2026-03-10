#!/usr/bin/env node
import fs from 'fs'
import Ajv2020 from 'ajv/dist/2020.js'

const [, , schemaPath, jsonPath] = process.argv

if (!schemaPath || !jsonPath) {
  console.error('usage: ri_validate_json.mjs <schema> <json>')
  process.exit(2)
}

const schema = JSON.parse(fs.readFileSync(schemaPath, 'utf8'))
const data = JSON.parse(fs.readFileSync(jsonPath, 'utf8'))

const ajv = new Ajv2020({ allErrors: true, strict: false })
const validate = ajv.compile(schema)
const ok = validate(data)

if (!ok) {
  console.error(JSON.stringify(validate.errors, null, 2))
  process.exit(1)
}

console.log('VALID')
