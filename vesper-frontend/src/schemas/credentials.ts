import { z } from "zod";

// Validacion del formulario de alta de credencial BYOK en /settings. El
// backend nunca devuelve la api_key (solo key_hint), asi que esta es la unica
// vez que el valor completo existe en el cliente: vive en el form state de
// react-hook-form y se descarta con `reset()` en cuanto se envia.
export const credentialFormSchema = z.object({
  provider_id: z.string().min(1, "Selecciona un proveedor"),
  api_key: z.string().min(1, "La API key es obligatoria"),
  label: z.string().max(80, "Máximo 80 caracteres").optional(),
});

export type CredentialFormValues = z.infer<typeof credentialFormSchema>;
