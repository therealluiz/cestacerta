{products.map((p) => {
  const best = p.offers[0];
  return (
    <article key={p.id} className="product">
      {p.image_url && (
        <img src={p.image_url} alt={p.name} className="product-img" />
      )}
      <h3>{p.name}</h3>
      <div className="offers">
        {p.offers.map((o) => (
          <span
            key={o.slug}
            className={`offer ${o === best ? "best" : ""}`}
          >
            {o.retailer} {brl(o.price)}
          </span>
        ))}
      </div>
      <button className="add" onClick={() => add(p)}>
        + Adicionar a cesta
      </button>
    </article>
  );
})}