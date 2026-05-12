import creds from "./test-credentials.json";

export interface TestUser {
  id: string;
  email: string;
  password: string;
  is_admin: boolean;
}

export const credentials: { testUser: TestUser; adminUser: TestUser } = creds;

export type UserType = keyof typeof credentials;
