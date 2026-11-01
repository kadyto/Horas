# Horas para Android

Versión independiente de Horas para **Android 8.0 o posterior**. Funciona sin servidor, sin conexión, sin cuenta y **sin contraseña**. Todos los registros se guardan en una base **SQLite privada en el dispositivo**. El APK sirve para dispositivos ARM y x86: no incluye bibliotecas nativas específicas de una arquitectura.

## Instalar

1. Descarga [Horas-1.1.1.apk](releases/Horas-1.1.1.apk) desde este directorio; en GitHub usa el botón de descarga del archivo.
2. Abre el APK en el dispositivo y permite instalar aplicaciones desde el navegador o gestor de archivos que estés usando, si Android lo solicita.
3. Abre **Horas**. Aparece directamente el calendario del mes actual.

El APK está firmado para instalación directa. No es necesario desplegar Docker, configurar variables ni conectarse a la versión web.

Su huella SHA-256 está publicada en [SHA256SUMS](releases/SHA256SUMS).

## Funciones

- Toca un día vacío para guardar 2 horas por defecto. Puedes configurar otra cantidad habitual o elegirla en el selector de registro rápido.
- Registra desde 0,25 hasta 24 horas por día, en intervalos de 15 minutos.
- Edita y elimina registros, con notas opcionales. Un segundo toque no duplica el día.
- Elige pago mensual o semanal, con semanas completas de lunes a domingo, incluso al cruzar de mes o año.
- Configura la tarifa habitual o la de un periodo concreto; cada registro conserva su precio al cambiar de modo.
- Consulta los acumulados mensuales, semanales y anuales, con cobrado, pendiente y estado parcial. Los cobros se comparten entre vistas por día.
- Guarda el mes en CSV o una copia de todos los datos en JSON usando el selector de archivos de Android.
- Importa copias JSON de la aplicación Android o de la versión web. La importación sustituye los datos locales tras una confirmación; una copia inválida no cambia la base de datos. Se conserva una copia previa que puedes guardar desde Ajustes.

Las reglas coinciden con la [versión web](../README.md#pago-mensual-y-semanal): minutos y céntimos enteros, tarifas conservadas por registro y redondeo por periodo. El año semanal usa semanas ISO completas. Cobrar un periodo marca sus días, sin duplicar cobros al cambiar de modo. Cambiar horas o precio devuelve los días afectados a pendiente; modificar solo una nota conserva el estado.

El APK 1.1.1 tiene la misma firma que los APK 1.0.0 y 1.1.0: instálalo como actualización, sin desinstalar. La migración de SQLite admite intervalos de 15 minutos y conserva los registros, tarifas, cobros y la forma de pago existentes. Las copias JSON de formato 1 también se pueden importar; las nuevas usan formato 2 y se intercambian con la web actualizada.

La fecha del mes actual procede del dispositivo. Cada instalación mantiene sus propios datos; no hay sincronización automática con otros dispositivos o con un servidor. **Desinstalar la aplicación o borrar sus datos elimina los registros locales.** Usa Ajustes → Guardar copia JSON para conservarlos o trasladarlos.

## Privacidad y funcionamiento

La aplicación **no solicita permiso de Internet** ni de acceso general al almacenamiento. La interfaz y todos sus recursos están incluidos en el APK y se muestran en un WebView local. La lógica de persistencia usa `SQLiteOpenHelper` de Android. El selector de documentos del sistema permite abrir y guardar únicamente los archivos que elijas.

No se usan autenticación, analíticas, cuentas, anuncios ni servicios externos. La aplicación no pide una contraseña al abrirse ni al guardar o restaurar registros.

## Compilar

Requisitos: JDK 21, SDK de Android con plataforma 35 y Build Tools 35.0.0. Configura `ANDROID_HOME` o `local.properties` con la ubicación del SDK.

```sh
cd android
bash gradlew :app:assembleDebug :app:testDebugUnitTest :app:lintDebug
```

El APK de desarrollo aparece en `app/build/outputs/apk/debug/app-debug.apk`.

Para compilar una versión de distribución con tu propia firma, configura estas variables locales:

```sh
export HORAS_KEYSTORE='/ruta/privada/horas-release.p12'
export HORAS_STORE_PASSWORD='contraseña-del-almacén-de-firma'
# El alias de la clave debe ser horas. HORAS_KEY_PASSWORD es opcional.
bash gradlew :app:assembleRelease
```

La contraseña del almacén de firma se usa exclusivamente al compilar; **no es una contraseña de acceso a la aplicación**. La clave de distribución y sus contraseñas se guardan fuera del repositorio público. Conserva la misma clave para que futuras versiones puedan actualizar una instalación existente sin desinstalarla.

El CSS y el reloj se incluyen desde `../app/static`; la compilación incorpora esos archivos al APK. La versión web y su contraseña de despliegue conservan su funcionamiento independiente.

## Verificación

- Pruebas JVM para fechas, intervalos de 15 minutos, tarifas y redondeo.
- Pruebas en emulador Android con SQLite real: persistencia, duplicados, ediciones obsoletas, tarifas históricas, cobros, CSV y restauración atómica.
- Arranque del WebView local, navegación a Ajustes, ausencia del permiso de Internet y apertura directa sin pantalla de acceso.
- `lintDebug` y compilación de los APK de aplicación y pruebas.

GitHub Actions ejecuta estas comprobaciones con el flujo `Android sin servidor`.
