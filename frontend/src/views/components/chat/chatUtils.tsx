import { FileAudio, FileVideo, File, Image as ImageIcon } from "lucide-react";
import { ChatAttachment } from "../../../models/types";

/** Returns an icon element for the given MIME type. */
export function fileIconFor(type: string) {
  if (type.startsWith("audio/")) return <FileAudio size={16} />;
  if (type.startsWith("video/")) return <FileVideo size={16} />;
  if (type.startsWith("image/")) return <ImageIcon size={16} />;
  return <File size={16} />;
}

/** Type guard: checks whether a value is a ChatAttachment object (not a plain string). */
export function isAttachmentObject(value: string | ChatAttachment): value is ChatAttachment {
  return typeof value === "object" && value !== null && "data" in value;
}

/** Returns a human-readable label for an attachment. */
export function attachmentLabel(attachment: string | ChatAttachment, index: number) {
  if (isAttachmentObject(attachment)) return attachment.name || `anexo-${index + 1}`;
  return `imagem-${index + 1}`;
}

/** Returns the MIME type for an attachment. */
export function attachmentType(attachment: string | ChatAttachment) {
  if (isAttachmentObject(attachment)) return attachment.type || "application/octet-stream";
  return "image/png";
}

/** Returns the base64 data string for an attachment. */
export function attachmentData(attachment: string | ChatAttachment) {
  return isAttachmentObject(attachment) ? attachment.data : attachment;
}

/** Checks whether an attachment is an image. */
export function isImageAttachment(attachment: string | ChatAttachment) {
  return attachmentType(attachment).startsWith("image/");
}
