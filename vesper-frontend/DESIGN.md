# Diseño de la interfaz de Vesper

Rediseño del 2026-10-15. El lenguaje visual viene del asistente de IA de otro producto de la
casa (Matriarca): neutros fríos, primario índigo, tarjetas con sombra suave, la conversación en
dos columnas. Este documento explica **por qué** se tomó cada decisión que se podría discutir.

## Medido antes de cambiar

La paleta anterior era la de serie de shadcn, toda en grises `oklch`. En gris acromático la
luminancia es L³, así que el contraste se calcula directo:

| Par | Antes | Mínimo |
|---|---|---|
| Borde de un campo sobre blanco | **1.26:1** | 3:1 (WCAG 1.4.11) |
| Anillo de foco sobre el lienzo | **2.59:1** | 3:1 |

Los dos fallaban: no se veía dónde escribir ni dónde estaba el foco del teclado.

`src/lib/contraste-tokens.test.ts` **lee `app/globals.css`** y comprueba 16 pares en los dos temas.
No tiene los hex copiados: si alguien cambia un token sin cumplir el contraste, la CI falla.

## Decisiones

**Índigo como primario y un dorado propio (`--star`) para la marca.** En el sistema de origen el
degradado del asistente usa `--accent`, que allí es el ámbar de *atención*. Usar un color de
estado como decoración enseña a ignorarlo. Vesper tiene su propio token de marca, el dorado de
la "estrella de la tarde" del banner del README, y el degradado índigo → dorado solo aparece en
la marca (avatar del agente, logotipo, botón de enviar). Nunca en un estado.

**El estado de un job se pinta por significado**, desde un solo sitio (`lib/jobs.ts`):
completado → éxito, falló → error, revisar → atención, trabajando → primario con pulso, en cola
→ neutro. Un estado nuevo que el frontend no conozca sale **neutro con su texto crudo**: no
hereda el color de otro y así no puede decir algo que no es. El texto acompaña siempre al color.

**Jobs es una conversación.** Cada job es literalmente un encargo y una respuesta del agente,
así que toma la forma del asistente: historial a la izquierda, hilo a la derecha y campo de
chat abajo. El campo vacío lanza la plantilla de la tarea; con texto es un prompt libre. Las
instrucciones exactas que recibió el agente se muestran plegadas: es la forma de saber qué se
le pidió de verdad.

**Una acción primaria por vista.** En Repositorios, «Vigilar» repetido 58 veces va en contorno:
cincuenta botones del color de acento significan que ninguno es el principal. Ajustes tiene dos
primarios («Añadir credencial» y «Guardar modelos»), pero cada uno cierra **su propio
formulario**, en tarjetas separadas: es la excepción consciente.

**En móvil la navegación va abajo.** Las cuatro secciones no caben arriba en 390 px: «Ajustes»
quedaba fuera de la pantalla con una barra de scroll horizontal. Medido en un móvil emulado.
Barra de pestañas fija abajo (patrón de PWA) y navegación arriba desde `sm`.

**El icono del tema lo elige el CSS, no React.** El servidor no conoce el tema del usuario;
pintar el icono según `resolvedTheme` producía un error de hidratación que hacía a React
regenerar la página, y la lista de jobs se quedaba cargando. Los dos iconos se renderizan
siempre y `dark:` decide cuál se ve.

**Los dos temas no son el mismo diseño invertido.** En claro, la elevación se marca con sombra y
borde; en oscuro, con contraste entre superficies (`--card` más claro que `--background`),
porque una sombra sobre fondo oscuro no se ve.

**El panel de marca del login va siempre oscuro.** Es una superficie de marca, como el banner
del README, no de la interfaz: no sigue el tema.

**Nada de versalitas decorativas** en títulos de sección ni en el historial.

## Primitivas

`components/ui/`: `Button` (primary, outline, ghost, destructive), `Input`/`Select`/`Textarea`/
`Label` (el contorno de 3:1 vive aquí), `Card`/`SectionTitle`, `StatusBadge` y `BrandMark`.
Antes de escribir clases a mano para un botón o un campo, usa estas.

## Fuera del sistema, a propósito

| Qué | Por qué |
|---|---|
| `themeColor` en `app/layout.tsx` (hex) | El navegador pinta su barra antes de que exista el CSS: no admite `var()` |
| Colores del panel de marca del login | Superficie de marca, fija en oscuro |
