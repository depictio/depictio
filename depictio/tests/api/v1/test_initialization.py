import boto3
from botocore.exceptions import ClientError
from bson import ObjectId
from unittest.mock import patch, MagicMock, call
import bcrypt
import mongomock
import os
import pymongo
import pytest
import shutil
import tempfile

# --------------------------------------------------------
# Test Initialization
# --------------------------------------------------------


class TestInitialization:
    def setup_method(self):
        # Set up patches for all dependencies
        self.s3_checks_patcher = patch(
            "depictio.api.v1.initialization.S3_storage_checks"
        )
        self.mock_s3_checks = self.s3_checks_patcher.start()

        self.generate_keys_patcher = patch(
            "depictio.api.v1.initialization.generate_keys"
        )
        self.mock_generate_keys = self.generate_keys_patcher.start()

        self.initialize_db_patcher = patch(
            "depictio.api.v1.initialization.initialize_db"
        )
        self.mock_initialize_db = self.initialize_db_patcher.start()

        self.create_bucket_patcher = patch(
            "depictio.api.v1.initialization.create_bucket"
        )
        self.mock_create_bucket = self.create_bucket_patcher.start()

        self.settings_patcher = patch("depictio.api.v1.initialization.settings")
        self.mock_settings = self.settings_patcher.start()

        # Configure mock settings
        self.mock_settings.auth.keys_algorithm = "RS256"
        self.mock_settings.auth.keys_dir = "/tmp/test_keys"
        self.mock_settings.mongodb.wipe = False

        # Mock return values
        self.mock_initialize_db.return_value = ("admin_user", "test_user")

    def teardown_method(self):
        # Stop all patches
        for patcher in [
            self.s3_checks_patcher,
            self.generate_keys_patcher,
            self.initialize_db_patcher,
            self.create_bucket_patcher,
            self.settings_patcher,
        ]:
            patcher.stop()

    def test_run_initialization_default_config(self):
        """Test initialization with default configuration."""
        from depictio.api.v1.initialization import (
            run_initialization,
            minios3_external_config,
        )

        # Run the function
        run_initialization()

        # Verify all steps were called in the correct order
        # self.mock_s3_checks.assert_called_once_with(minios3_external_config, ["s3"])
        self.mock_generate_keys.assert_called_once()
        self.mock_initialize_db.assert_called_once_with(wipe=False)
        self.mock_create_bucket.assert_called_once_with("admin_user")

    def test_run_initialization_custom_config(self):
        """Test initialization with custom S3 configuration."""
        from depictio.api.v1.initialization import run_initialization
        from depictio_models.models.s3 import S3DepictioCLIConfig

        s3_config = S3DepictioCLIConfig.parse_obj(
            {
                "endpoint_url": "https://custom-endpoint",
                "DEPICTIO_MINIO_ROOT_USER": "custom-key",
                "DEPICTIO_MINIO_ROOT_PASSWORD": "custom-secret",
                "bucket": "custom-bucket",
            }
        )

        # Create a custom S3 config
        # custom_config = MinioConfig(**s3_config, secure=True)
        print(f"Custom S3 config: {s3_config}")

        # Run with custom config
        run_initialization(s3_config=s3_config)

        # Verify S3 checks used the custom config
        # self.mock_s3_checks.assert_called_once_with(custom_config, ["s3"])
        self.mock_generate_keys.assert_called_once()
        self.mock_initialize_db.assert_called_once_with(wipe=False)
        self.mock_create_bucket.assert_called_once_with("admin_user")

    def test_run_initialization_custom_checks(self):
        """Test initialization with custom S3 checks."""
        from depictio.api.v1.initialization import run_initialization

        # Run with custom checks
        run_initialization(checks=["s3", "bucket"])

        # Verify custom checks were used
        # self.mock_s3_checks.assert_called_once_with(ANY, ["s3", "bucket"])
        self.mock_generate_keys.assert_called_once()
        self.mock_initialize_db.assert_called_once_with(wipe=False)
        self.mock_create_bucket.assert_called_once_with("admin_user")

    def test_run_initialization_with_db_wipe(self):
        """Test initialization with database wipe enabled."""
        from depictio.api.v1.initialization import run_initialization

        # Configure settings to enable wipe
        self.mock_settings.mongodb.wipe = True

        # Run initialization
        run_initialization()

        # Verify DB was initialized with wipe=True
        self.mock_initialize_db.assert_called_once_with(wipe=True)


# --------------------------------------------------------
# Integration Tests
# --------------------------------------------------------



def test_mongodb_connection():
    """Test if MongoDB is accessible on the specified port."""
    import pymongo
    try:
        client = pymongo.MongoClient("mongodb://localhost:27018", serverSelectionTimeoutMS=5000)
        # Force a connection to verify server is available
        client.server_info()
        print("MongoDB connection successful")
        return True
    except Exception as e:
        print(f"MongoDB connection failed: {e}")
        return False


@pytest.mark.integration
def test_initialization_integration():
    """Integration test for the initialization process with real S3 connection."""
    # Create a temporary directory for keys
    test_dir = tempfile.mkdtemp()
    print("Step 1: Created temporary directory")
    
    # Store original environment variables to restore later
    original_env = {}
    env_vars_to_modify = {
        "DEPICTIO_AUTH_KEYS_DIR": test_dir,
        "DEPICTIO_MONGODB_DB_NAME": "depictioDB-test",
        "DEPICTIO_MONGODB_URL": "mongodb://localhost:27018",
        "DEPICTIO_MONGODB_SERVICE_NAME": "localhost",
        # Use the real S3 credentials
        "DEPICTIO_MINIO_ROOT_USER": "Q3AM3UQ867SPQQA43P2F",
        "DEPICTIO_MINIO_ROOT_PASSWORD": "zuf+tfteSlswRu7BJ86wekitnifILbZam1KYY3TG",
        "DEPICTIO_MINIO_EXTERNAL_ENDPOINT": "https://play.min.io",
        "DEPICTIO_MINIO_BUCKET": "depictio-bucket-test",
    }
    
    # Save original values and set test values
    for var, value in env_vars_to_modify.items():
        original_env[var] = os.environ.get(var)
        os.environ[var] = value
    print("Step 2: Set environment variables")
    
    # Test bucket name - use a unique name to avoid conflicts
    test_bucket_name = f"depictio-bucket-test-{os.getpid()}"
    os.environ["DEPICTIO_MINIO_BUCKET"] = test_bucket_name
    print(f"Test bucket name: {test_bucket_name}")
    
    # Check MongoDB connection first
    if not test_mongodb_connection():
        pytest.skip("MongoDB not available on port 27018, skipping integration test")
    

    from depictio.api.v1.configs.config import settings
    print(f"Settings: {settings}")

    try:
        # Import the function first to check if import works
        print("Step 3: Importing initialization module")
        from depictio.api.v1.initialization import run_initialization
        print("Step 4: Successfully imported run_initialization")
        
        # Run with timeout to prevent hanging
        print("Step 5: About to run initialization")
        test = run_initialization()
        print("Step 6: Initialization completed successfully")
        
        # Rest of the test...
    # except Exception as e:
    #     print(f"Error during initialization: {e}")
    #     import traceback
    #     traceback.print_exc()
    #     raise
    # finally:
    #     # Cleanup code...
    #     print("Cleanup: Restoring environment")
    #     for var, value in original_env.items():
    #         if value is None:
    #             os.environ.pop(var, None)
    #         else:
    #             os.environ[var] = value

        # 2. Verify database was initialized with correct users
        # Connect to the test database
        client = pymongo.MongoClient(os.environ["DEPICTIO_MONGODB_URL"])
        db = client[os.environ["DEPICTIO_MONGODB_DBTEST_NAME"]]
        
        # Check if admin user exists
        admin = db.users.find_one({"email": "admin@depictio.com"})
        assert admin is not None, "Admin user was not created"
        assert admin["is_admin"] is True, "Admin user does not have admin privileges"
        
        # Check if test user exists
        test = db.users.find_one({"email": "test@depictio.com"})
        assert test is not None, "Test user was not created"
        
        # Check if required groups exist
        admin_group = db.groups.find_one({"name": "admin"})
        users_group = db.groups.find_one({"name": "users"})
        assert admin_group is not None, "Admin group was not created"
        assert users_group is not None, "Users group was not created"
        
    #     # 3. Verify S3 bucket was created and is accessible
    #     # Create an S3 client
    #     s3_client = boto3.client(
    #         's3',
    #         endpoint_url=os.environ["DEPICTIO_MINIO_EXTERNAL_ENDPOINT"],
    #         aws_access_key_id=os.environ["DEPICTIO_MINIO_ROOT_USER"],
    #         aws_secret_access_key=os.environ["DEPICTIO_MINIO_ROOT_PASSWORD"],
    #         # use_ssl=True,
    #         # verify=True,
    #         region_name='us-east-1'  # Default region for S3 compatibility
    #     )
        
    #     # Check if the bucket exists
    #     try:
    #         s3_client.head_bucket(Bucket=test_bucket_name)
    #         bucket_exists = True
    #     except ClientError as e:
    #         # If a 404 error is returned, the bucket doesn't exist
    #         error_code = int(e.response['Error']['Code'])
    #         if error_code == 404:
    #             bucket_exists = False
    #         else:
    #             # If another error occurred, re-raise it
    #             raise
        
    #     assert bucket_exists, f"Bucket {test_bucket_name} was not created"
        
    #     # 4. Test writing and reading from the bucket
    #     test_key = 'depictio-test-file.txt'
    #     test_content = b'This is a test file for the initialization integration test'
        
    #     # Upload a test file
    #     s3_client.put_object(
    #         Bucket=test_bucket_name,
    #         Key=test_key,
    #         Body=test_content
    #     )
        
    #     # Download the test file
    #     response = s3_client.get_object(
    #         Bucket=test_bucket_name,
    #         Key=test_key
    #     )
        
    #     # Verify the content
    #     downloaded_content = response['Body'].read()
    #     assert downloaded_content == test_content, "S3 read/write test failed"
        
    #     # 5. Verify the function returned the expected users
    #     assert admin_user is not None, "Admin user was not returned"
    #     assert test_user is not None, "Test user was not returned"
        
    finally:
        # Clean up
        # 1. Remove temporary directory
        shutil.rmtree(test_dir)
        
    #     # 2. Clean up S3 bucket
    #     try:
    #         # Delete all objects in the bucket
    #         s3_client = boto3.client(
    #             's3',
    #             endpoint_url=os.environ["DEPICTIO_MINIO_EXTERNAL_ENDPOINT"],
    #             aws_access_key_id=os.environ["DEPICTIO_MINIO_ROOT_USER"],
    #             aws_secret_access_key=os.environ["DEPICTIO_MINIO_ROOT_PASSWORD"],
    #             use_ssl=True,
    #             verify=True,
    #             region_name='us-east-1'
    #         )
            
    #         # List all objects in the bucket
    #         response = s3_client.list_objects_v2(Bucket=test_bucket_name)
            
    #         if 'Contents' in response:
    #             for obj in response['Contents']:
    #                 s3_client.delete_object(
    #                     Bucket=test_bucket_name,
    #                     Key=obj['Key']
    #                 )
            
    #         # Delete the bucket
    #         s3_client.delete_bucket(Bucket=test_bucket_name)
    #     except Exception as e:
    #         print(f"Warning: Could not clean up S3 bucket: {e}")
        
        # 3. Clean up test database
        try:
            client = pymongo.MongoClient(os.environ.get("DEPICTIO_MONGODB_URI", "mongodb://localhost:27017"))
            client.drop_database("test_db")
        except Exception as e:
            print(f"Warning: Could not clean up test database: {e}")
        
    #     # 4. Restore original environment variables
    #     for var, value in original_env.items():
    #         if value is None:
    #             os.environ.pop(var, None)
    #         else:
    #             os.environ[var] = value