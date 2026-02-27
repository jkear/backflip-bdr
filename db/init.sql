-- Create schemas
CREATE SCHEMA IF NOT EXISTS crm;
CREATE SCHEMA IF NOT EXISTS obs;
CREATE SCHEMA IF NOT EXISTS improve;

-- Grant the application user ownership of all schemas
ALTER SCHEMA crm OWNER TO backflip;
ALTER SCHEMA obs OWNER TO backflip;
ALTER SCHEMA improve OWNER TO backflip;
