# Code Review Helper

Perform code review on changes or specific files.

## Instructions

When reviewing code:

1. **Gather changes to review**:
   - If no arguments: review staged changes (`git diff --cached`)
   - If file path: review that specific file
   - If PR number: fetch and review PR changes

2. **Review criteria** (in order of priority):

   **Security**:
   - SQL/NoSQL injection vulnerabilities
   - Command injection risks
   - XSS vulnerabilities
   - Sensitive data exposure
   - Authentication/authorization issues

   **Type Safety**:
   - Proper type annotations
   - None handling
   - Union type guards
   - Pydantic model validation

   **Code Quality**:
   - Following depictio patterns
   - Proper error handling
   - Logging appropriateness
   - Code duplication
   - Function/method complexity

   **Performance**:
   - N+1 query patterns
   - Missing async/await
   - Unnecessary database calls
   - Memory leaks in callbacks

   **Testing**:
   - Test coverage for new code
   - Edge cases handled
   - Mock usage appropriateness

3. **Provide feedback**:
   - List issues by severity (Critical, Warning, Info)
   - Include file:line references
   - Suggest specific fixes
   - Highlight good patterns found

## Usage

`/review` - Review staged git changes
`/review <file>` - Review specific file
`/review pr <number>` - Review pull request

$ARGUMENTS
