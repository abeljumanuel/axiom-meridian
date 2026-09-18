# Reglas Globales de Código Limpio - Robert C. Martin

> Basado en "Clean Code: A Handbook of Agile Software Craftsmanship" por Robert C. Martin
> Estas reglas aplican a **todos los lenguajes de programación** y definen estándares universales de calidad de código.

---

## RN-GLOBAL-001
**Scope:** global
**Categoría:** naming
**Severidad:** critical
**Aplica a:** *
**Tags:** clean-code, naming, readability, universal
**Fuente:** clean-code-robert-martin-ch2
**Regla:** Usa nombres que revelen intención. Un nombre debe responder: por qué existe, qué hace y cómo se usa. Evita nombres que requieran comentarios para explicarse. Prefiere `elapsedTimeInDays` sobre `d` o `elapsed`. Nunca uses nombres desinformativos como `accountList` a menos que sea realmente una lista.

---

## RN-GLOBAL-002
**Scope:** global
**Categoría:** naming
**Severidad:** high
**Aplica a:** *
**Tags:** clean-code, naming, booleans, universal
**Fuente:** clean-code-robert-martin-ch2
**Regla:** Los nombres de variables booleanas deben ser predicados (afirmación verdadera/falsa). Usa `isEmpty`, `isValid`, `hasPermission`, `shouldRetry`, `canExecute` en lugar de `status`, `flag`, `enabled`. Nunca uses negaciones en nombres (`isNotValid` → `isInvalid`).

---

## RN-GLOBAL-003
**Scope:** global
**Categoría:** naming
**Severidad:** high
**Aplica a:** *
**Tags:** clean-code, naming, constants, universal
**Fuente:** clean-code-robert-martin-ch2
**Regla:** Las constantes mágicas deben tener nombres descriptivos. Extrae valores literales con significado semántico a constantes con nombre: `MAX_RETRIES = 3`, `DAYS_IN_WEEK = 7`, `PI = 3.14159`. Nunca dejes números o strings "hardcodeados" sin explicar su propósito.

---

## RN-GLOBAL-004
**Scope:** global
**Categoría:** functions
**Severidad:** critical
**Aplica a:** *
**Tags:** clean-code, functions, single-responsibility, universal
**Fuente:** clean-code-robert-martin-ch3
**Regla:** Las funciones deben hacer UNA sola cosa. Una función hace una sola cosa si no puedes extraer otra función de ella con un nombre que no sea una reimplementación. Si la función mezcla niveles de abstracción (ej: validar input + escribir a base de datos), viola este principio.

---

## RN-GLOBAL-005
**Scope:** global
**Categoría:** functions
**Severidad:** critical
**Aplica a:** *
**Tags:** clean-code, functions, size, universal
**Fuente:** clean-code-robert-martin-ch3
**Regla:** Las funciones deben ser pequeñas (máximo 20 líneas) y hacer UNA sola cosa. Si una función no cabe completamente en pantalla sin hacer scroll, es demasiado grande. Las funciones pequeñas son más fáciles de entender, probar y reutilizar.

---

## RN-GLOBAL-006
**Scope:** global
**Categoría:** functions
**Severidad:** high
**Aplica a:** *
**Tags:** clean-code, functions, parameters, universal
**Fuente:** clean-code-robert-martin-ch3
**Regla:** Minimiza el número de parámetros. Ideal: 0 parámetros. Aceptable: 1-2 parámetros. Máximo recomendado: 3 parámetros. Si necesitas más, considera crear un objeto/struct que agrupe los parámetros relacionados. Los booleanos como parámetros violan SRP (hacen dos cosas según el flag).

---

## RN-GLOBAL-007
**Scope:** global
**Categoría:** functions
**Severidad:** high
**Aplica a:** *
**Tags:** clean-code, functions, side-effects, universal
**Fuente:** clean-code-robert-martin-ch3
**Regla:** Las funciones no deben tener side effects ocultos. Una función debe hacer lo que su nombre promete y nada más. Si una función llamada `checkPassword` también inicializa una sesión, tiene un side effect oculto que sorprenderá a quien la use.

---

## RN-GLOBAL-008
**Scope:** global
**Categoría:** comments
**Severidad:** critical
**Aplica a:** *
**Tags:** clean-code, comments, documentation, universal
**Fuente:** clean-code-robert-martin-ch4
**Regla:** Los comentarios no compensan código malo. No uses comentarios para explicar código confuso; refactoriza el código para que se explique solo. Los comentarios mienten (el código cambia, los comentarios no siempre). El código es la única fuente de verdad.

---

## RN-GLOBAL-009
**Scope:** global
**Categoría:** comments
**Severidad:** medium
**Aplica a:** *
**Tags:** clean-code, comments, legal, intent, universal
**Fuente:** clean-code-robert-martin-ch4
**Regla:** Solo comenta información que el código no puede expresar: licencias/copyright, explicaciones de decisión de diseño (por qué, no qué), advertencias de consecuencias, TODOs con número de issue. Evita comentarios obvios (`// incrementa i`), de journal, o código comentado.

---

## RN-GLOBAL-010
**Scope:** global
**Categoría:** formatting
**Severidad:** high
**Aplica a:** *
**Tags:** clean-code, formatting, readability, vertical-density, universal
**Fuente:** clean-code-robert-martin-ch5
**Regla:** El formato vertical transmite significado. Conceptos relacionados deben estar verticalmente cercanos. El espacio vertical separa ideas, la densidad vertical las agrupa. Las variables deben declararse cerca de su uso. Las funciones llamadas deben estar cerca de quien las llama (arriba de preferencia).

---

## RN-GLOBAL-011
**Scope:** global
**Categoría:** formatting
**Severidad:** medium
**Aplica a:** *
**Tags:** clean-code, formatting, indentation, horizontal, universal
**Fuente:** clean-code-robert-martin-ch5
**Regla:** Mantén líneas cortas (máximo 80-120 caracteres). Usa indentación para mostrar jerarquía de scope. Rompe líneas largas en puntos naturales (después de coma, antes de operador). Agrupa operaciones relacionadas horizontalmente con espacios consistentes alrededor de operadores.

---

## RN-GLOBAL-012
**Scope:** global
**Categoría:** objects-structures
**Severidad:** critical
**Aplica a:** *
**Tags:** clean-code, oop, encapsulation, data-hiding, universal
**Fuente:** clean-code-robert-martin-ch6
**Regla:** Oculta la estructura interna. Los objetos deben ocultar sus datos y exponer operaciones. No expongas detalles de implementación (getters/setters que exponen estructuras internas). Si un método devuelve una estructura interna, viola encapsulación. Prefiere objetos que HACEN cosas sobre objetos que tienen datos.

---

## RN-GLOBAL-013
**Scope:** global
**Categoría:** error-handling
**Severidad:** critical
**Aplica a:** *
**Tags:** clean-code, error-handling, exceptions, universal
**Fuente:** clean-code-robert-martin-ch7
**Regla:** Usa excepciones, no códigos de error. Las funciones deben hacer UNA cosa: o devolver un valor, o lanzar excepción, nunca ambos. No uses excepciones para flujo de control normal. Las excepciones deben ser inesperadas, no casos de negocio predecibles.

---

## RN-GLOBAL-014
**Scope:** global
**Categoría:** error-handling
**Severidad:** high
**Aplica a:** *
**Tags:** clean-code, error-handling, context, universal
**Fuente:** clean-code-robert-martin-ch7
**Regla:** Las excepciones deben ser informativas. Incluye contexto suficiente para determinar la fuente y ubicación del error. Un mensaje como "Array index out of bounds" sin decir qué array, índice o tamaño no ayuda. Incluye valores relevantes, nombres de operaciones fallidas.

---

## RN-GLOBAL-015
**Scope:** global
**Categoría:** boundaries
**Severidad:** high
**Aplica a:** *
**Tags:** clean-code, boundaries, third-party, interfaces, universal
**Fuente:** clean-code-robert-martin-ch8
**Regla:** Aísla código de terceros. No dejes que código de terceros invada tu código base. Usa wrappers, adapters o facades para aislar dependencias externas. Esto permite cambiar la biblioteca sin afectar todo el código, y hace que tu código sea más testeable.

---

## RN-GLOBAL-016
**Scope:** global
**Categoría:** testing
**Severidad:** critical
**Aplica a:** *
**Tags:** clean-code, testing, tdd, universal
**Fuente:** clean-code-robert-martin-ch9
**Regla:** Las pruebas son tan importantes como el código de producción. Las pruebas deben ser legibles, mantenibles y rápidas. Una prueba debe verificar UNA sola cosa (una aserción por prueba conceptual). Usa el patrón Arrange-Act-Assert (Given-When-Then). Las pruebas deben ser independientes y determinísticas.

---

## RN-GLOBAL-017
**Scope:** global
**Categoría:** classes
**Severidad:** critical
**Aplica a:** *
**Tags:** clean-code, classes, srp, cohesion, universal
**Fuente:** clean-code-robert-martin-ch10
**Regla:** Las clases deben ser pequeñas y seguir SRP (Single Responsibility Principle). Una clase debe tener una sola razón para cambiar. Si puedes describir la responsabilidad de una clase con "y" o "o", tiene más de una responsabilidad. Las clases deben tener alta cohesión: todos sus métodos deben usar todas sus variables de instancia.

---

## RN-GLOBAL-018
**Scope:** global
**Categoría:** dry
**Severidad:** critical
**Aplica a:** *
**Tags:** clean-code, dry, duplication, universal
**Fuente:** clean-code-robert-martin-ch12
**Regla:** DRY - Don't Repeat Yourself. Cada pieza de conocimiento debe tener una única, inequívoca representación autoritativa en el sistema. La duplicación es el principal enemigo del sistema bien diseñado. Cuando cambies algo, no deberías tener que recordar múltiples lugares donde cambiarlo.

---

## RN-GLOBAL-019
**Scope:** global
**Categoría:** complexity
**Severidad:** high
**Aplica a:** *
**Tags:** clean-code, simplicity, boy-scout-rule, universal
**Fuente:** clean-code-robert-martin-ch1
**Regla:** La regla del Boy Scout: Deja el campamento más limpio de lo que lo encontraste. Cada vez que toques un archivo, deja el código un poco mejor que como lo encontraste. Si todos hacemos esto, el código base mejorará constantemente. No necesitas "permiso" para refactorizar código que tocas.

---

## RN-GLOBAL-020
**Scope:** global
**Categoría:** complexity
**Severidad:** high
**Aplica a:** *
**Tags:** clean-code, simplicity, minimalism, universal
**Fuente:** lean-software-dev
**Regla:** Mantén simple todo lo que puedas. No construyas lo que no necesitas ahora (YAGNI - You Aren't Gonna Need It). Cada línea de código es una responsabilidad. El código que no existe es el único código sin bugs. Prefiere soluciones simples que funcionan sobre arquitecturas complejas para casos hipotéticos futuros.

---

## RN-GLOBAL-021
**Scope:** global
**Categoría:** control-flow
**Severidad:** medium
**Aplica a:** *
**Tags:** clean-code, conditionals, nesting, universal
**Fuente:** clean-code-robert-martin-ch3
**Regla:** Evita el anidamiento profundo. Usa cláusulas de guarda (guard clauses) para retornar temprano de funciones. Prefiere `if (!valid) return;` sobre anidar todo el código dentro de un if. El código debe leerse de arriba hacia abajo, no de izquierda a derecha con múltiples niveles de indentación.

---

## RN-GLOBAL-022
**Scope:** global
**Categoría:** control-flow
**Severidad:** medium
**Aplica a:** *
**Tags:** clean-code, conditionals, positive, universal
**Fuente:** clean-code-robert-martin-ch3
**Regla:** Prefiere condicionales positivos. Es más fácil entender `if (isValid)` que `if (!isInvalid)`. Cuando niegues, extrae a una variable con nombre descriptivo: `const userNotFound = !user; if (userNotFound)` es mejor que `if (!user)`.

---

## RN-GLOBAL-023
**Scope:** global
**Categoría:** functions
**Severidad:** high
**Aplica a:** *
**Tags:** clean-code, functions, switch, polymorphism, universal
**Fuente:** clean-code-robert-martin-ch3
**Regla:** Evita sentencias switch (o equivalentes). Las sentencias switch violan SRP, OCP y tienen duplicación inherente. Usa polimorfismo en su lugar. Si debes usar switch, ocúltalo tras una abstracción y nunca repitas la misma estructura switch en múltiples lugares.

---

## RN-GLOBAL-024
**Scope:** global
**Categoría:** concurrency
**Severidad:** high
**Aplica a:** *
**Tags:** clean-code, concurrency, synchronization, universal
**Fuente:** clean-code-robert-martin-ch13
**Regla:** Separa la lógica de concurrencia del código de negocio. El código concurrente debe ser pequeño y enfocado. La concurrencia es un detalle de implementación que debe aislarse. Evita compartir estado mutable entre hilos; cuando sea necesario, sincroniza acceso y minimiza la sección crítica.

---

## RN-GLOBAL-025
**Scope:** global
**Categoría:** code-smells
**Severidad:** critical
**Aplica a:** *
**Tags:** clean-code, code-smells, refactoring, universal
**Fuente:** clean-code-robert-martin-ch17
**Regla:** Elimina code smells inmediatamente. Code smells incluyen: funciones largas, clases grandes, lists of parameters largas, duplicación, feature envy (clase que usa más métodos de otra que de sí misma), data clumps (grupos de variables que siempre viajan juntas), dead code (código no usado). Cada smell es una oportunidad de mejora.

---

## RN-GLOBAL-026
**Scope:** global
**Categoría:** variables
**Severidad:** high
**Aplica a:** *
**Tags:** clean-code, variables, scope, universal
**Fuente:** clean-code-robert-martin-ch3
**Regla:** Minimiza el scope de las variables. Declara variables lo más cerca posible de su uso. Las variables de instancia deben usarse en muchos métodos de la clase; si no, deberían ser locales. Las variables deben vivir el menor tiempo posible para reducir el estado mental necesario para entender el código.

---

## RN-GLOBAL-027
**Scope:** global
**Categoría:** environment
**Severidad:** high
**Aplica a:** *
**Tags:** clean-code, environment, build, universal
**Fuente:** clean-code-robert-martin-ch6
**Regla:** El build debe ser automático y de un paso. Un nuevo desarrollador debe poder clonar el repositorio y ejecutar un solo comando para construir el sistema. El build debe incluir todas las pruebas y ser determinístico (mismos inputs = mismos outputs).

---

## RN-GLOBAL-028
**Scope:** global
**Categoría:** environment
**Severidad:** high
**Aplica a:** *
**Tags:** clean-code, environment, testing, ci, universal
**Fuente:** clean-code-robert-martin-ch6
**Regla:** Ejecuta todas las pruebas en cada commit. El sistema de integración continua debe ejecutar la suite completa de pruebas automáticamente. Las pruebas deben ser rápidas (segundos, no minutos) para mantener el flujo de trabajo ágil. Una prueba que no corre es una prueba rota.

---

## RN-GLOBAL-029
**Scope:** global
**Categoría:** dependencies
**Severidad:** medium
**Aplica a:** *
**Tags:** clean-code, dependencies, law-of-demeter, universal
**Fuente:** clean-code-robert-martin-ch6
**Regla:** Sigue la Ley de Demeter. Un método de un objeto solo debe llamar a métodos de: 1) sí mismo, 2) sus parámetros, 3) objetos que crea, 4) sus atributos directos. Evita "train wrecks": `obj.getA().getB().doSomething()` (excepto fluent APIs intencionales). Cada punto en una cadena de llamadas es un acoplamiento.

---

## RN-GLOBAL-030
**Scope:** global
**Categoría:** null-safety
**Severidad:** high
**Aplica a:** *
**Tags:** clean-code, null, safety, defensive-programming, universal
**Fuente:** clean-code-robert-martin-ch7
**Regla:** Evita retornar null. En lugar de retornar null, lanza una excepción o retorna un objeto especial (Null Object pattern). Cada retorno de null es una invitación a NullPointerException/NullReferenceException. Valida inputs en los límites del sistema y convierte nulls a excepciones o valores por defecto tempranamente.

---
