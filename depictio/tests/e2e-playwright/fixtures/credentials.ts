import creds from "./test-credentials.json";

export interface TestUser {
  id: string;
  email: string;
  password: string;
  is_admin: boolean;
}

/**
 * Test users seeded by the backend bootstrap (db_init.py:
 * _bootstrap_admin_and_test_user) from the DEPICTIO_BOOTSTRAP_* env vars in
 * docker-compose/.env. The JSON defaults mirror the committed dev values;
 * override via env when targeting a stack seeded with different secrets:
 *   PLAYWRIGHT_ADMIN_PASSWORD / PLAYWRIGHT_TEST_USER_PASSWORD
 */
export const credentials: { testUser: TestUser; adminUser: TestUser } = {
  testUser: {
    ...creds.testUser,
    password: process.env.PLAYWRIGHT_TEST_USER_PASSWORD ?? creds.testUser.password,
  },
  adminUser: {
    ...creds.adminUser,
    password: process.env.PLAYWRIGHT_ADMIN_PASSWORD ?? creds.adminUser.password,
  },
};

export type UserType = keyof typeof credentials;
