import { redirect } from "next/navigation";

// Reports are now attached inside a conversation.
export default function UploadRedirect() {
  redirect("/patient");
}
