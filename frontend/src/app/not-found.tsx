import Link from "next/link";

export default function NaoEncontrada() {
  return (
    <div className="mx-auto max-w-7xl px-5 py-20 sm:px-10">
      <h1 className="font-serif text-4xl font-bold">Licitação não encontrada</h1>
      <Link href="/" className="mt-6 inline-block underline underline-offset-4">
        Voltar para a lista
      </Link>
    </div>
  );
}
