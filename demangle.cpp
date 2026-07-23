#include "binaryninjaapi.h"
#include <string>
#include <utility>
using namespace std;
using namespace BinaryNinja;

namespace {
	std::optional<DemanglerResult> DemangleWithDemangler(
		const BNDemangler* demangler, const Platform* platform, const std::string& mangledName, bool simplify)
	{
		if (!demangler)
			return std::nullopt;

		BNDemanglerConfig apiConfig(platform ? platform->GetObject() : nullptr, nullptr, simplify);
		BNDemanglerResult apiResult = {};
		if (!BNDemangleWithDemangler(demangler, mangledName.c_str(), &apiConfig, &apiResult))
			return std::nullopt;

		return DemanglerResult::FromAPIObjectAndFree(&apiResult);
	}
}

namespace BinaryNinja
{
	DemanglerConfig::DemanglerConfig(Platform* platform, BinaryView* view, bool simplifyTemplates) :
		platform(platform), view(view), simplifyTemplates(simplifyTemplates)
	{}


	DemanglerConfig DemanglerConfig::FromAPIObject(const BNDemanglerConfig* config)
	{
		if (!config)
			return Default();

		DemanglerConfig result(
			config->platform ? new CorePlatform(BNNewPlatformReference(config->platform)) : Default().platform.GetPtr(),
			nullptr, config->simplifyTemplates);
		if (config->view)
		{
			result.m_viewOwner = new BinaryView(BNNewViewReference(config->view));
			result.view = result.m_viewOwner;
		}
		return result;
	}


	DemanglerConfig DemanglerConfig::Default()
	{
		BNDemanglerConfig config = BNGetDefaultDemanglerConfig();
		static auto cfg = FromAPIObject(&config);
		return cfg;
	}

	DemanglerConfig DemanglerConfig::ForPlatform(Platform* platform, bool simplifyTemplates)
	{
		return {platform ? platform : Default().platform.GetPtr(), nullptr, simplifyTemplates};
	}

	DemanglerConfig DemanglerConfig::ForBinaryView(BinaryView* view)
	{
		if (!view)
			return Default();

		Ref<Platform> platform = view->GetDefaultPlatform();
		if (!platform)
		{
			if (auto arch = view->GetDefaultArchitecture())
				platform = arch->GetStandalonePlatform();
		}
		if (!platform)
			platform = Default().platform;

		return {platform, view,
			Settings::Instance()->Get<bool>("analysis.types.templateSimplifier", view)};
	}

	Platform& DemanglerConfig::GetPlatform() const
	{
		if (platform)
			return *platform;
		return *Default().platform;
	}

	BNDemanglerConfig DemanglerConfig::ToAPIObject() const
	{
		return {
			GetPlatform().GetObject(),
			view ? view->GetObject() : nullptr,
			simplifyTemplates,
		};
	}

	DemanglerResult DemanglerResult::FromAPIObject(const BNDemanglerResult* apiResult)
	{
		DemanglerResult result;
		if (!apiResult)
			return result;

		result.name = QualifiedName::FromAPIObject(&apiResult->name);
		if (apiResult->type)
			result.type = new Type(BNNewTypeReference(apiResult->type));
		else
			result.type = nullptr;
		return result;
	}

	DemanglerResult DemanglerResult::FromAPIObjectAndFree(BNDemanglerResult* apiResult)
	{
		DemanglerResult result = FromAPIObject(apiResult);
		BNFreeDemanglerResult(apiResult);
		return result;
	}

	BNDemanglerResult DemanglerResult::ToAPIObject() const
	{
		return {
			name.GetAPIObject(),
			type ? BNNewTypeReference(type->m_object) : nullptr,
		};
	}

	std::optional<DemanglerResult> DemangleLLVM(const std::string& mangledName, bool simplify)
	{
		return DemangleWithDemangler(BNGetLLVMDemangler(), nullptr, mangledName, simplify);
	}


	std::optional<DemanglerResult> DemangleMS(
		const Platform* platform, const std::string& mangledName, bool simplify)
	{
		return DemangleWithDemangler(BNGetMSVCDemangler(), platform, mangledName, simplify);
	}


	std::optional<DemanglerResult> DemangleGNU3(
		const Platform* platform, const std::string& mangledName, bool simplify)
	{
		return DemangleWithDemangler(BNGetGNU3Demangler(), platform, mangledName, simplify);
	}


	bool IsMSVCMangledString(const std::string& mangledName)
	{
		BNDemangler* demangler = BNGetMSVCDemangler();
		return demangler && BNIsDemanglerMangledName(demangler, mangledName.c_str());
	}


	bool IsGNU3MangledString(const std::string& mangledName)
	{
		BNDemangler* demangler = BNGetGNU3Demangler();
		return demangler && BNIsDemanglerMangledName(demangler, mangledName.c_str());
	}

	QualifiedName SimplifyDemangledTemplateName(const QualifiedName& name)
	{
		BNQualifiedName apiName = name.GetAPIObject();
		BNQualifiedName apiResult = {};
		if (!BNSimplifyDemangledTemplateName(&apiName, &apiResult))
		{
			QualifiedName::FreeAPIObject(&apiName);
			return name;
		}

		QualifiedName result = QualifiedName::FromAPIObject(&apiResult);
		QualifiedName::FreeAPIObject(&apiName);
		BNFreeQualifiedName(&apiResult);
		return result;
	}

	Demangler::Demangler(std::string demanglerName): m_nameForRegister(std::move(demanglerName))
	{
	}

	Demangler::Demangler(BNDemangler* demangler)
	{
		m_object = demangler;
	}

	bool Demangler::IsMangledStringCallback(void* ctxt, const char* mangledName)
	{
		auto demangler = static_cast<Demangler*>(ctxt);
		return demangler->IsMangledString(mangledName);
	}

	bool Demangler::DemangleCallback(void* ctxt, const char* mangledName, const BNDemanglerConfig* config,
		BNDemanglerResult* result)
	{
		auto demangler = static_cast<Demangler*>(ctxt);

		if (!mangledName || !result)
			return false;

		auto demangleResult = demangler->Demangle(mangledName, DemanglerConfig::FromAPIObject(config));
		if (!demangleResult)
			return false;

		*result = demangleResult->ToAPIObject();
		return true;
	}

	void Demangler::FreeResultCallback(void* ctxt, BNDemanglerResult* result)
	{
		BNFreeDemanglerResult(result);
	}

	bool Demangler::Register(Demangler* demangler)
	{
		if (!demangler)
			return false;

		BNDemanglerCallbacks cb = {};
		cb.size = sizeof(cb);
		cb.context = reinterpret_cast<void*>(demangler);
		cb.isMangledString = IsMangledStringCallback;
		cb.demangle = DemangleCallback;
		cb.freeResult = FreeResultCallback;
		BNDemangler* object = BNRegisterDemangler(demangler->m_nameForRegister.c_str(), &cb);
		if (!object)
			return false;

		demangler->m_object = object;
		return true;
	}

	bool Demangler::Promote(const Ref<Demangler>& demangler)
	{
		if (!demangler || !demangler->m_object)
			return false;
		return BNPromoteDemangler(demangler->m_object);
	}

	std::vector<Ref<Demangler>> Demangler::GetList()
	{
		size_t count;
		BNDemangler** list = BNGetDemanglerList(&count);
		vector<Ref<Demangler>> result;
		result.reserve(count);
		for (size_t i = 0; i < count; i++)
			result.push_back(new CoreDemangler(list[i]));
		BNFreeDemanglerList(list);
		return result;
	}

	Ref<Demangler> Demangler::GetByName(const std::string& demanglerName)
	{
		BNDemangler* result = BNGetDemanglerByName(demanglerName.c_str());
		if (!result)
			return nullptr;
		return new CoreDemangler(result);
	}

	std::optional<Demangler::Result> Demangler::DemangleAny(const std::string& mangledName, const Config& config)
	{
		BNDemanglerConfig apiConfig = config.ToAPIObject();
		BNDemanglerResult apiResult = {};
		if (!BNDemangle(mangledName.c_str(), &apiConfig, &apiResult))
			return std::nullopt;

		return Result::FromAPIObjectAndFree(&apiResult);
	}

	std::string Demangler::GetName() const
	{
		char* name = BNGetDemanglerName(m_object);
		std::string value = name;
		BNFreeString(name);
		return value;
	}

	CoreDemangler::CoreDemangler(BNDemangler* demangler): Demangler(demangler)
	{
	}

	bool CoreDemangler::IsMangledString(const std::string& name)
	{
		return BNIsDemanglerMangledName(m_object, name.c_str());
	}

	std::optional<Demangler::Result> CoreDemangler::Demangle(const std::string& name, const Config& config)
	{
		BNDemanglerConfig apiConfig = config.ToAPIObject();
		BNDemanglerResult apiResult = {};
		bool success = BNDemangleWithDemangler(m_object, name.c_str(), &apiConfig, &apiResult);

		if (!success)
			return std::nullopt;

		return Result::FromAPIObjectAndFree(&apiResult);
	}
}  // namespace BinaryNinja
