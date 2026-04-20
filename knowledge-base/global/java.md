## RN-JAVA-001
**Scope:** global-java
**Categoría:** architecture
**Severidad:** critical
**Aplica a:** **/*.java
**Tags:** imperative, reactive, quarkus
**Fuente:** tech-lead-directive-2026-01
**Regla:** Imperative model only — Java 21 (Temurin) + Quarkus. No Mutiny, no reactive extensions. All code must be synchronous/imperative.

## RN-JAVA-002
**Scope:** global-java
**Categoría:** logging
**Severidad:** critical
**Aplica a:** **/*.java
**Tags:** slf4j, fluent-api, datadog, structured-logging
**Fuente:** tech-lead-directive-2026-01
**Regla:** Always use @Slf4j (Lombok) with the SLF4J Fluent API for structured logging compatible with Datadog. Never use org.jboss.logging.Logger or Logger.getLogger(). Use key-value pairs over string interpolation.

## RN-JAVA-003
**Scope:** global-java
**Categoría:** dependency-injection
**Severidad:** high
**Aplica a:** **/*.java
**Tags:** cdi, constructor-injection, lombok
**Fuente:** tech-lead-directive-2026-01
**Regla:** Constructor injection over field injection. Prefer @RequiredArgsConstructor or explicit constructors over @Inject on fields. Omit @Inject on single-constructor beans (CDI 4.0 auto-discovers). Exception: required when @ConfigProperty params are present or multiple constructors exist.
