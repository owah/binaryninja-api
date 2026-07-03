use binaryninja::architecture::{ArchitectureExt, CoreArchitecture};
use binaryninja::demangle::{
    demangle_any, demangle_generic, demangle_gnu3, demangle_llvm, demangle_ms, CustomDemangler,
    Demangler, DemanglerConfig, DemanglerResult,
};
use binaryninja::headless::Session;
use binaryninja::types::{QualifiedName, Type};
use std::sync::OnceLock;

struct TestDemangler;

impl CustomDemangler for TestDemangler {
    fn is_mangled_string(&self, name: &str) -> bool {
        name == "test_name" || name == "test_name2"
    }

    fn demangle(&self, name: &str, config: &DemanglerConfig) -> Option<DemanglerResult> {
        match name {
            "test_name" => Some(DemanglerResult::new(
                QualifiedName::from(vec![if config.simplify_templates {
                    "test_name_simplified"
                } else {
                    "test_name"
                }]),
                Some(Type::bool()),
            )),
            "test_name2" => Some(DemanglerResult::new(
                QualifiedName::from(vec!["test_name2", "aaa"]),
                None,
            )),
            _ => None,
        }
    }
}

fn register_custom_demangler() {
    static CUSTOM_DEMANGLER: OnceLock<()> = OnceLock::new();
    CUSTOM_DEMANGLER.get_or_init(|| {
        assert!(Demangler::register("Test", TestDemangler));
    });
}

fn session() -> &'static Session {
    static SESSION: OnceLock<Session> = OnceLock::new();
    SESSION.get_or_init(|| {
        register_custom_demangler();
        Session::new().expect("Failed to initialize session")
    })
}

#[test]
fn test_demangler_simple() {
    let _session = session();
    let placeholder_arch = CoreArchitecture::by_name("x86_64").expect("x86_64 exists");
    // Example LLVM-style mangled name
    let llvm_mangled = "_Z3fooi"; // "foo(int)" in LLVM mangling
    let llvm_demangled = demangle_llvm(llvm_mangled, true).unwrap();
    assert_eq!(llvm_demangled, "foo(int)".into());

    // Example GNU-style mangled name
    let gnu_mangled = "_Z3bari"; // "bar(int)" in GNU mangling
    let gnu_demangled = demangle_gnu3(&placeholder_arch, gnu_mangled, true).unwrap();
    assert_eq!(gnu_demangled.name, "bar".into());
    // TODO: We check the type display because other means include things such as confidence which is hard to get 1:1
    assert_eq!(
        gnu_demangled.ty.unwrap().to_string(),
        "int64_t(int32_t)".to_string()
    );

    // Example MSVC-style mangled name
    let msvc_mangled = "?baz@@YAHH@Z"; // "int __cdecl baz(int)" in MSVC mangling
    let msvc_demangled = demangle_ms(&placeholder_arch, msvc_mangled, true).unwrap();
    assert_eq!(msvc_demangled.name, "baz".into());
    // TODO: We check the type display because other means include things such as confidence which is hard to get 1:1
    assert_eq!(
        msvc_demangled.ty.unwrap().to_string(),
        "int32_t __cdecl(int32_t)".to_string()
    );
}

#[test]
fn test_custom_demangler() {
    let _session = session();
    let placeholder_arch = CoreArchitecture::by_name("x86_64").expect("x86_64 exists");
    let platform = placeholder_arch
        .standalone_platform()
        .expect("x86_64 standalone platform exists");
    let config = DemanglerConfig::for_platform(&platform, true);

    let demangled = demangle_any("test_name", &config).unwrap();
    assert_eq!(
        demangled,
        DemanglerResult::new(
            QualifiedName::from(vec!["test_name_simplified"]),
            Some(Type::bool())
        )
    );
    let unsimplified = demangle_generic(&placeholder_arch, "test_name", None, false).unwrap();
    assert_eq!(
        unsimplified,
        DemanglerResult::new(QualifiedName::from(vec!["test_name"]), Some(Type::bool()))
    );
    let demangled2 = demangle_generic(&placeholder_arch, "test_name2", None, true).unwrap();
    assert_eq!(
        demangled2,
        DemanglerResult::new(QualifiedName::from(vec!["test_name2", "aaa"]), None)
    );
}
