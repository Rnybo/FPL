export default function ComingSoon({ title }: { title: string }) {
  return (
    <div className="p-6 max-w-3xl mx-auto text-center py-24">
      <h1 className="text-xl font-semibold text-slate-900">{title}</h1>
      <p className="text-slate-400 mt-2 text-sm">Not built yet — Player Scout was the first page wired end-to-end.</p>
    </div>
  )
}
