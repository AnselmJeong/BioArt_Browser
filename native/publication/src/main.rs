//! Isolated local SVG normalization/PDF converter. No network or external image files.
use serde_json::{json, Value};
use std::{collections::BTreeSet, env, fs, path::Path, sync::Mutex};
use svg2pdf::{usvg, ConversionOptions, PageOptions};
static LOGS: Mutex<Vec<String>> = Mutex::new(Vec::new());
struct Logger;
impl log::Log for Logger {
    fn enabled(&self, m: &log::Metadata) -> bool {m.level() <= log::Level::Warn}
    fn log(&self, r: &log::Record) {if self.enabled(r.metadata()) {let mut logs=LOGS.lock().unwrap(); if logs.len()<200 {logs.push(r.args().to_string());}}}
    fn flush(&self) {}
}
static LOGGER: Logger = Logger;
fn rect(r: usvg::Rect)->Value {json!([r.x(),r.y(),r.width(),r.height()])}
fn scale(t: usvg::Transform)->(f32,f32) {
    let trace=t.sx*t.sx+t.ky*t.ky+t.kx*t.kx+t.sy*t.sy;
    let det=(t.sx*t.sy-t.kx*t.ky).powi(2);
    let d=(trace*trace-4.0*det).max(0.0).sqrt();
    (((trace-d)/2.0).max(0.0).sqrt(),((trace+d)/2.0).max(0.0).sqrt())
}
fn walk(group:&usvg::Group, tree:&usvg::Tree, context:usvg::Transform, owner:&str, records:&mut Vec<Value>, fonts:&mut BTreeSet<String>, missing:&mut BTreeSet<String>, restricted:&mut BTreeSet<String>) {
    for node in group.children() {
        let id=if node.id().starts_with("n-") {node.id()} else {owner};
        match node {
            usvg::Node::Group(g)=> {
                if !g.id().is_empty() {records.push(json!({"kind":"bounds","id":g.id(),"owner":id,"bounds":rect(g.abs_stroke_bounding_box())}));}
                if !g.filters().is_empty() {
                    let parent=context.pre_concat(g.abs_transform()).pre_concat(g.transform().invert().unwrap_or_default());
                    let (_,parent_scale)=scale(parent);
                    if let Some(bounds)=g.layer_bounding_box().transform(g.transform()) {
                        records.push(json!({"kind":"filter","owner":id,"count":g.filters().len(),"parentScale":parent_scale,"width":bounds.width(),"height":bounds.height()}));
                    }
                }
                if g.opacity().get()<1.0 {records.push(json!({"kind":"transparency","owner":id}));}
                walk(g,tree,context,id,records,fonts,missing,restricted);
            }
            usvg::Node::Text(t)=> {
                let (small,_) = scale(context.pre_concat(t.abs_transform()));
                let mut requested=BTreeSet::new();
                for chunk in t.chunks() {for span in chunk.spans() {for f in span.font().families(){requested.insert(f.to_string().trim_matches('"').to_string());}}}
                let mut actual=BTreeSet::new();
                for span in t.layouted() {
                    records.push(json!({"kind":"text","owner":id,"size":span.font_size.get()*small}));
                    for glyph in &span.positioned_glyphs {
                        if glyph.id.0==0&&!glyph.text.trim().is_empty(){missing.insert(glyph.text.clone());}
                        if let Some(face)=tree.fontdb().face(glyph.font) {
                            actual.insert(face.post_script_name.clone());fonts.insert(face.post_script_name.clone());
                            let blocked=tree.fontdb().with_face_data(glyph.font,|data,index|ttf_parser::Face::parse(data,index).map(|f|!f.is_outline_embedding_allowed()||!f.is_subsetting_allowed()||format!("{:?}",f.permissions()).contains("Restricted")).unwrap_or(true)).unwrap_or(true);
                            if blocked {restricted.insert(face.post_script_name.clone());}
                        }
                    }
                }
                records.push(json!({"kind":"fonts","owner":id,"requested":requested,"actual":actual}));
            }
            usvg::Node::Path(p)=> {
                if let Some(stroke)=p.stroke(){let (small,_)=scale(context.pre_concat(p.abs_transform())); records.push(json!({"kind":"stroke","owner":id,"width":stroke.width().get()*small}));}
                if p.fill().is_some_and(|v|v.opacity().get()<1.0)||p.stroke().is_some_and(|v|v.opacity().get()<1.0){records.push(json!({"kind":"transparency","owner":id}));}
            }
            usvg::Node::Image(i)=> {
                let matrix=context.pre_concat(i.abs_transform());
                if let usvg::ImageKind::SVG(inner)=i.kind(){walk(inner.root(),inner,matrix,id,records,fonts,missing,restricted);}else{
                    let (_,large)=scale(matrix);
                    records.push(json!({"kind":"raster","owner":id,"width":i.size().width(),"height":i.size().height(),"pixelsPerUnit":1.0/large.max(0.000001)}));
                }
            }
        }
    }
}
fn run()->Result<(),Box<dyn std::error::Error>> {
    let args:Vec<_>=env::args().collect();
    if args.len()!=7 {return Err("Usage: bioart-publication input.svg output-dir width-mm dpi outline|embed analyze|export".into());}
    let input=fs::read_to_string(&args[1])?;
    if input.len()>100_000_000{return Err("SVG exceeds conversion limit".into());}
    let dir=Path::new(&args[2]);let width_mm:f32=args[3].parse()?;let dpi:f32=args[4].parse()?;
    if !(10.0..=1000.0).contains(&width_mm)||!(72.0..=2400.0).contains(&dpi){return Err("Invalid dimensions".into());}
    if !["outline","embed"].contains(&args[5].as_str())||!["analyze","export"].contains(&args[6].as_str()){return Err("Invalid operation".into());}
    let mut options=usvg::Options::default();options.fontdb_mut().load_system_fonts();options.fontdb_mut().set_sans_serif_family("Helvetica Neue");
    options.image_href_resolver.resolve_string=Box::new(|_,_|None);
    let tree=usvg::Tree::from_str(&input,&options)?;
    let mut records=Vec::new();let mut fonts=BTreeSet::new();let mut missing=BTreeSet::new();let mut restricted=BTreeSet::new();
    walk(tree.root(),&tree,usvg::Transform::identity(),"",&mut records,&mut fonts,&mut missing,&mut restricted);
    let families:BTreeSet<_>=tree.fontdb().faces().flat_map(|f|f.families.iter().map(|(s,_)|s.clone())).collect();
    let base_scale=width_mm/25.4*dpi/tree.size().width();
    let parent_scale=records.iter().filter(|r|r["kind"]=="filter").filter_map(|r|r["parentScale"].as_f64()).fold(1.0_f64,f64::max) as f32;
    let raster_scale=base_scale*parent_scale;
    let filter_pixels: f64=records.iter().filter(|r|r["kind"]=="filter").map(|r|r["width"].as_f64().unwrap_or(0.0)*r["height"].as_f64().unwrap_or(0.0)*(raster_scale as f64).powi(2)).sum();
    fs::create_dir_all(dir)?;
    fs::write(dir.join("analysis.json"),serde_json::to_vec_pretty(&json!({"engine":"svg2pdf 0.13 / usvg 0.45.1","filterPixels":filter_pixels,"records":records,"fonts":fonts,"availableFamilies":families,"missingGlyphs":missing,"restrictedFonts":restricted,"warnings":*LOGS.lock().unwrap()}))?)?;
    if args[6]=="analyze" {return Ok(());}
    if filter_pixels>50_000_000.0{return Err("Filter rasterization exceeds 50 megapixel memory limit".into());}
    if !missing.is_empty(){return Err("Some glyphs are missing. Resolve preflight errors before export.".into());}
    if args[5]=="embed"&&!restricted.is_empty(){return Err("Font embedding restrictions detected. Choose outlines.".into());}
    let options=ConversionOptions{embed_text:args[5]=="embed",raster_scale:raster_scale.max(0.1),..Default::default()};
    let pdf=svg2pdf::to_pdf(&tree,options,PageOptions{dpi:tree.size().width()*25.4/width_mm}).map_err(|e|format!("PDF conversion failed: {e:?}"))?;
    fs::write(dir.join("figure.pdf"),pdf)?;
    fs::write(dir.join("outlined.svg"),tree.to_string(&usvg::WriteOptions::default()))?;
    Ok(())
}
fn main(){log::set_logger(&LOGGER).unwrap();log::set_max_level(log::LevelFilter::Warn);if let Err(e)=run(){eprintln!("{e}");std::process::exit(1);}}
