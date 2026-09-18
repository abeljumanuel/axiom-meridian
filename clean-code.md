# Global Clean Code Rules - Robert C. Martin

> Based on "Clean Code: A Handbook of Agile Software Craftsmanship" by Robert C. Martin
> These rules apply to **all programming languages** and define universal quality standards.

---

## Naming

### Use intention-revealing names
- **Domain**: naming
- **Severity**: critical
- **Rule**: Use names that reveal intention. A name should answer why it exists, what it does, and how it is used. Avoid names that require comments to explain themselves. Prefer `elapsedTimeInDays` over `d` or `elapsed`. Never use misleading names like `accountList` unless it is really a list.

### Boolean names as predicates
- **Domain**: naming
- **Severity**: high
- **Rule**: Boolean variable names should be predicates (true/false statements). Use `isEmpty`, `isValid`, `hasPermission`, `shouldRetry`, `canExecute` instead of `status`, `flag`, `enabled`. Never use negations in names (`isNotValid` → `isInvalid`).

### Magic constants with descriptive names
- **Domain**: naming
- **Severity**: high
- **Rule**: Magic constants should have descriptive names. Extract literal values with semantic meaning to named constants: `MAX_RETRIES = 3`, `DAYS_IN_WEEK = 7`, `PI = 3.14159`. Never leave hardcoded numbers or strings without explaining their purpose.

---

## Functions

### Functions should do ONE thing
- **Domain**: functions
- **Severity**: critical
- **Rule**: Functions should do ONE thing. A function does one thing if you cannot extract another function from it with a name that is not merely a reimplementation. If the function mixes abstraction levels (e.g., validate input + write to database), it violates this principle.

### Functions should be small
- **Domain**: functions
- **Severity**: critical
- **Rule**: Functions should be small (maximum 20 lines) and do ONE thing. If a function does not fit completely on screen without scrolling, it is too large. Small functions are easier to understand, test, and reuse.

### Minimize the number of parameters
- **Domain**: functions
- **Severity**: high
- **Rule**: Minimize the number of parameters. Ideal: 0 parameters. Acceptable: 1-2 parameters. Maximum recommended: 3 parameters. If you need more, consider creating an object/struct that groups related parameters. Booleans as parameters violate SRP (they make functions do two things based on the flag).

### Functions without hidden side effects
- **Domain**: functions
- **Severity**: high
- **Rule**: Functions should not have hidden side effects. A function should do what its name promises and nothing more. If a function called `checkPassword` also initializes a session, it has a hidden side effect that will surprise callers.

### Avoid switch statements
- **Domain**: functions
- **Severity**: high
- **Rule**: Avoid switch statements (or equivalents). Switch statements violate SRP, OCP, and have inherent duplication. Use polymorphism instead. If you must use switch, hide it behind an abstraction and never repeat the same switch structure in multiple places.

---

## Comments

### Comments do not compensate for bad source
- **Domain**: comments
- **Severity**: critical
- **Rule**: Comments do not compensate for bad source. Do not use comments to explain confusing source; refactor the source to be self-explanatory. Comments lie (the source changes, comments do not always). The source is the single source of truth.

### When to use comments
- **Domain**: comments
- **Severity**: medium
- **Rule**: Only comment information that the source cannot express: licenses/copyright, explanations of design decisions (why, not what), warnings of consequences, TODOs with issue numbers. Avoid obvious comments (`// increment i`), journal comments, or commented-out source.

---

## Formatting

### Vertical format conveys meaning
- **Domain**: formatting
- **Severity**: high
- **Rule**: Vertical format conveys meaning. Related concepts should be vertically close. Vertical space separates ideas; vertical density groups them. Variables should be declared close to their use. Called functions should be close to their callers (preferably above).

### Keep lines short
- **Domain**: formatting
- **Severity**: medium
- **Rule**: Keep lines short (maximum 80-120 characters). Use indentation to show scope hierarchy. Break long lines at natural points (after commas, before operators). Group related operations horizontally with consistent spacing around operators.

---

## Objects and Structures

### Hide internal structure
- **Domain**: objects-structures
- **Severity**: critical
- **Rule**: Hide internal structure. Objects should hide their data and expose operations. Do not expose implementation details (getters/setters that expose internal structures). If a method returns an internal structure, it violates encapsulation. Prefer objects that DO things over objects that HAVE data.

---

## Error Handling

### Use exceptions not error codes
- **Domain**: error-handling
- **Severity**: critical
- **Rule**: Use exceptions, not error codes. Functions should do ONE thing: either return a value or throw an exception, never both. Do not use exceptions for normal control flow. Exceptions should be unexpected, not predictable business cases.

### Informative exceptions
- **Domain**: error-handling
- **Severity**: high
- **Rule**: Exceptions should be informative. Include sufficient context to determine the source and location of the error. A message like "Array index out of bounds" without saying which array, index, or size does not help. Include relevant values, names of failed operations.

---

## Boundaries

### Isolate third-party source
- **Domain**: boundaries
- **Severity**: high
- **Rule**: Isolate third-party source. Do not let third-party source invade your base. Use wrappers, adapters, or facades to isolate external dependencies. This allows changing the library without affecting all the source, and makes your source more testable.

---

## Testing

### Tests as important as production source
- **Domain**: testing
- **Severity**: critical
- **Rule**: Tests are as important as production source. Tests should be readable, maintainable, and fast. A test should verify ONE thing (one assertion per test conceptually). Use the Arrange-Act-Assert pattern (Given-When-Then). Tests should be independent and deterministic.

---

## Classes

### Small classes with SRP
- **Domain**: classes
- **Severity**: critical
- **Rule**: Classes should be small and follow SRP (Single Responsibility Principle). A class should have only one reason to change. If you can describe a class's responsibility with "and" or "or", it has more than one responsibility. Classes should have high cohesion: all their methods should use all their instance variables.

---

## DRY

### Do not repeat yourself
- **Domain**: dry
- **Severity**: critical
- **Rule**: DRY - Do not Repeat Yourself. Every piece of knowledge must have a single, unambiguous, authoritative representation in the system. Duplication is the primary enemy of a well-designed system. When you change something, you should not have to remember multiple places to change it.

---

## Complexity

### Boy Scout Rule
- **Domain**: complexity
- **Severity**: high
- **Rule**: The Boy Scout Rule: Leave the campground cleaner than you found it. Every time you touch a file, leave the source a little better than you found it. If we all do this, the base will constantly improve. You do not need "permission" to refactor source you touch.

### Keep everything as simple as possible
- **Domain**: complexity
- **Severity**: high
- **Rule**: Keep everything as simple as possible. Do not build what you do not need now (YAGNI - You Will not Need It). Every line of source is a liability. The source that does not exist is the only source without bugs. Prefer simple solutions that work over complex architectures for hypothetical future cases.

---

## Control Flow

### Avoid deep nesting
- **Domain**: control-flow
- **Severity**: medium
- **Rule**: Avoid deep nesting. Use guard clauses to return early from functions. Prefer `if (!valid) return;` over nesting all the source inside an if. Source should read top-to-bottom, not left-to-right with multiple indentation levels.

### Prefer positive conditionals
- **Domain**: control-flow
- **Severity**: medium
- **Rule**: Prefer positive conditionals. It is easier to understand `if (isValid)` than `if (!isInvalid)`. When you must negate, extract to a descriptively named variable: `const userNotFound = !user; if (userNotFound)` is better than `if (!user)`.

---

## Concurrency

### Separate concurrency logic from business
- **Domain**: concurrency
- **Severity**: high
- **Rule**: Separate concurrency logic from business logic. Concurrent source should be small and focused. Concurrency is an implementation detail that should be isolated. Avoid sharing mutable state between threads; when necessary, synchronize access and minimize the critical section.

---

## Code Smells

### Eliminate code smells immediately
- **Domain**: code-smells
- **Severity**: critical
- **Rule**: Eliminate code smells immediately. Code smells include: long functions, large classes, long parameter lists, duplication, feature envy (class that uses more methods from another than itself), data clumps (groups of variables that always travel together), dead source (unused source). Every smell is an opportunity for improvement.

---

## Variables

### Minimize variable scope
- **Domain**: variables
- **Severity**: high
- **Rule**: Minimize variable scope. Declare variables as close as possible to their use. Instance variables should be used by many methods of the class; if not, they should be local. Variables should live the shortest time possible to reduce the mental state needed to understand the source.

---

## Environment

### One-step automated build
- **Domain**: environment
- **Severity**: high
- **Rule**: The build should be automated and one-step. A new developer should be able to clone the repository and run a single command to build the system. The build should include all tests and be deterministic (same inputs = same outputs).

### Run all tests on every commit
- **Domain**: environment
- **Severity**: high
- **Rule**: Run all tests on every commit. The continuous integration system should run the complete test suite automatically. Tests should be fast (seconds, not minutes) to maintain agile workflow. A test that does not run is a broken test.

---

## Dependencies

### Follow Law of Demeter
- **Domain**: dependencies
- **Severity**: medium
- **Rule**: Follow the Law of Demeter. An object's method should only call methods of: 1) itself, 2) its parameters, 3) objects it creates, 4) its direct attributes. Avoid "train wrecks": `obj.getA().getB().doSomething()` (except intentional fluent APIs). Each dot in a call chain is coupling.

---

## Null Safety

### Avoid returning null
- **Domain**: null-safety
- **Severity**: high
- **Rule**: Avoid returning null. Instead of returning null, throw an exception or return a special object (Null Object pattern). Every null return is an invitation to NullPointerException/NullReferenceException. Validate inputs at system boundaries and convert nulls to exceptions or default values early.

---
